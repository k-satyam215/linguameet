import asyncio
import time

from app.config import Settings
from app.languages import DEFAULT_REGISTRY
from app.latency import Metrics
from app.pipeline import TranslationPipeline, Utterance, looks_like_hallucination
from app.providers.base import ASRResult, ProviderError, RateLimited
from app.providers.mock import MockASR, MockTranslator
from app.vad import Segment


def make_segment(now: float | None = None) -> Segment:
    now = time.monotonic() if now is None else now
    return Segment(pcm=b"\x01\x00" * 16000, duration_ms=1000, detected_at=now, hangover_ms=450)


class Collector:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, audience, event):
        self.events.append((audience, event))

    def of(self, audience=None, kind=None, final=None):
        return [
            e for a, e in self.events
            if (audience is None or a == audience)
            and (kind is None or e.get("kind") == kind)
            and (final is None or e.get("final") == final)
        ]


def make(asr=None, translator=None, **settings):
    m = Metrics()
    p = TranslationPipeline(asr or MockASR(), translator or MockTranslator(), DEFAULT_REGISTRY, m, Settings(**settings))
    return p, m


async def test_original_caption_then_translation_per_language():
    p, m = make()
    c = Collector()
    utt = Utterance("u1", "Rahul", "hi", make_segment())
    text = await p.process(utt, {"en", "fr"}, [], [], c)
    assert text
    assert len(c.of("*all", "original")) == 1
    assert c.of("lang:en", "translation", True)[0]["text"].startswith("[English]")
    assert c.of("lang:fr", "translation", True)[0]["text"].startswith("[French]")
    # the original caption must come before any translation
    assert c.events[0][1]["kind"] == "original"


async def test_same_language_listener_gets_no_translation_call():
    p, _ = make()
    c = Collector()
    await p.process(Utterance("u1", "A", "en", make_segment()), {"en"}, [], [], c)
    assert c.of(kind="translation") == []
    assert len(c.of("*all", "original")) == 1


async def test_hindi_and_hinglish_are_not_translated_into_each_other():
    p, _ = make()
    c = Collector()
    await p.process(Utterance("u1", "A", "hi-en", make_segment()), {"hi"}, [], [], c)
    assert c.of(kind="translation") == []


async def test_partials_stream_before_final():
    p, _ = make(translator=MockTranslator(delay_s=0.06))
    c = Collector()
    await p.process(Utterance("u1", "A", "hi", make_segment()), {"en"}, [], [], c)
    tr = c.of("lang:en", "translation")
    assert len(tr) >= 2
    assert tr[-1]["final"] is True
    assert all(not e["final"] for e in tr[:-1])
    assert "e2e_ms" in tr[-1]["timings"]


async def test_metrics_are_recorded():
    p, m = make()
    await p.process(Utterance("u1", "A", "hi", make_segment()), {"en"}, [], [], Collector())
    stages = m.summary()["stages"]
    for k in ("asr_ms", "translate_total_ms", "e2e_final_ms", "e2e_first_token_ms"):
        assert k in stages, k
    # end-to-end includes the VAD hangover
    assert stages["e2e_final_ms"]["p50_ms"] >= 450


class FailingASR:
    name = "fail"

    def __init__(self, exc):
        self.exc = exc

    async def transcribe(self, *a, **k):
        raise self.exc


async def test_asr_rate_limit_is_reported_not_retried_in_a_loop():
    p, m = make(asr=FailingASR(RateLimited(1)))
    c = Collector()
    assert await p.process(Utterance("u1", "A", "hi", make_segment()), {"en"}, [], [], c) is None
    assert c.of("*speaker")[0]["code"] == "rate_limited"
    assert m.counters["asr_rate_limited"] == 1


async def test_asr_failure_is_reported():
    p, _ = make(asr=FailingASR(ProviderError("boom")))
    c = Collector()
    await p.process(Utterance("u1", "A", "hi", make_segment()), {"en"}, [], [], c)
    assert c.of("*speaker")[0]["code"] == "asr_failed"


class SlowTranslator(MockTranslator):
    async def translate_stream(self, *a, **k):
        await asyncio.sleep(5)
        yield "never"


async def test_translation_timeout_emits_status_and_keeps_original():
    p, m = make(translator=SlowTranslator(), translate_timeout_s=0.1)
    c = Collector()
    await p.process(Utterance("u1", "A", "hi", make_segment()), {"en"}, [], [], c)
    assert len(c.of("*all", "original")) == 1
    assert any(e["code"] == "translate_failed" for _, e in c.events if e["type"] == "status")
    assert m.counters["translate_failed"] == 1


async def test_stale_work_is_dropped_explicitly():
    p, m = make(stale_after_s=1.0)
    c = Collector()
    seg = make_segment(now=0.0)
    await p.process(Utterance("u1", "A", "hi", seg), {"en"}, [], [], c, clock=lambda: 50.0)
    assert c.of(kind="translation") == []
    assert m.counters["stale_dropped"] == 1


class EmptyASR:
    name = "empty"

    async def transcribe(self, *a, **k):
        return ASRResult(text="Thank you.", language="en")


async def test_whisper_silence_hallucination_is_filtered():
    p, m = make(asr=EmptyASR())
    c = Collector()
    assert await p.process(Utterance("u1", "A", "en", make_segment()), {"hi"}, [], [], c) is None
    assert c.events == []
    assert m.counters["asr_empty"] == 1


def test_hallucination_detector():
    assert looks_like_hallucination("Thank you.")
    assert looks_like_hallucination(" ")
    assert not looks_like_hallucination("Kal deployment hai")


class RecordingTranslator(MockTranslator):
    def __init__(self):
        super().__init__()
        self.seen = None

    async def translate_stream(self, text, source_name, target_name, glossary, context, note):
        self.seen = (source_name, target_name, glossary, context, note)
        yield "ok"


async def test_glossary_context_and_hinglish_note_reach_translator():
    t = RecordingTranslator()
    p, _ = make(translator=t)
    await p.process(Utterance("u1", "A", "hi-en", make_segment()), {"en"}, ["RepoMind"], ["prev sentence"], Collector())
    src, tgt, gloss, ctx, note = t.seen
    assert (src, tgt) == ("Hinglish", "English")
    assert gloss == ["RepoMind"] and ctx == ["prev sentence"]
    assert "Hinglish" in note


async def test_auto_source_uses_detected_language():
    class DetectASR:
        name = "d"

        async def transcribe(self, *a, **k):
            return ASRResult(text="hello there everyone", language="english")

    p, _ = make(asr=DetectASR())
    c = Collector()
    await p.process(Utterance("u1", "A", "auto", make_segment()), {"hi", "en"}, [], [], c)
    assert c.of("*all", "original")[0]["lang"] == "en"
    assert c.of("lang:en", "translation") == []     # same as detected source
    assert c.of("lang:hi", "translation", True)
