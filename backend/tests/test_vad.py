from app.vad import VadConfig, VadSegmenter

from .helpers import chunks, silence, tone, utterance_audio


def feed_all(seg: VadSegmenter, data: bytes):
    out = []
    for c in chunks(data):
        out.extend(seg.feed(c))
    return out


def test_pure_silence_yields_nothing():
    assert feed_all(VadSegmenter(), silence(3000)) == []


def test_one_utterance_is_segmented():
    out = feed_all(VadSegmenter(), utterance_audio(700, 800))
    assert len(out) == 1
    s = out[0]
    assert 600 <= s.duration_ms <= 1300
    assert s.hangover_ms == 450
    assert not s.forced


def test_two_utterances_are_two_segments():
    audio = utterance_audio(600, 700) + utterance_audio(600, 700)
    assert len(feed_all(VadSegmenter(), audio)) == 2


def test_short_blip_is_ignored():
    assert feed_all(VadSegmenter(), silence(200) + tone(80) + silence(900)) == []


def test_long_speech_is_force_cut():
    cfg = VadConfig(max_segment_ms=1000)
    out = feed_all(VadSegmenter(cfg), silence(100) + tone(3500) + silence(800))
    assert len(out) >= 3
    assert any(s.forced for s in out)


def test_split_chunks_do_not_lose_frames():
    seg = VadSegmenter()
    audio = utterance_audio(700, 800)
    out = []
    # awkward 333-byte chunks that never align with 640-byte frames
    for i in range(0, len(audio), 333):
        out.extend(seg.feed(audio[i:i + 333]))
    assert len(out) == 1


def test_flush_returns_pending_speech():
    seg = VadSegmenter()
    feed_all(seg, silence(100) + tone(800))
    assert seg.speaking
    s = seg.flush()
    assert s is not None and s.forced
