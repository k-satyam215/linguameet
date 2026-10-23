# Thesis evaluation protocol (LinguaMeet)

## Scope and research questions

The application is a working real-time meeting prototype. The thesis contribution is a reproducible comparison and measured latency/quality analysis, not a claim that one model is universally best.

1. How do ASR and translation quality vary by language and code-switching condition?
2. What end-to-end latency and quality trade-offs result from configurable speech segmentation and VAD settings?
3. How does the production Groq pipeline compare with a locally run Indic-language translation baseline such as AI4Bharat IndicTrans2 on the exact same, human-checked utterances?

## Evaluation artifacts in this repository

`backend/scripts/evaluate.py` scores exported system outputs without calling a provider. Every prediction row is JSONL with the fields below. `id` must identify the same utterance across all systems; `model` names the complete system/configuration; `task` is `asr` or `translation`; `language` is the evaluated language (for translation, the target language).

```json
{"id":"hi_001","model":"groq-whisper-v3-turbo","task":"asr","language":"hi","reference":"कल बैठक है","hypothesis":"कल बैठक है","timings_ms":{"asr":236,"first_translation":776,"end_to_end":790}}
{"id":"hi-en_001","model":"indictrans2-v1","task":"translation","language":"hi","reference":"कृपया कल बैठक का एजेंडा भेजें।","hypothesis":"कृपया कल मीटिंग का एजेंडा भेजें।"}
```

Run `cd backend; python -m scripts.evaluate predictions.jsonl --require-paired --output metrics.json`. The evaluator reports WER/CER for ASR, hypothesis/reference token ratio, mean smoothed sentence BLEU and character F-score for translations, and p50/p95 for every supplied timing field. It reports how many IDs are paired across model outputs. Use the *same references and utterance IDs* for every compared model. Keep original audio, transcripts, outputs and manifest versioned separately from code when consent allows; never commit private recordings or identifying data.

Metrics are computed on the provided text as-is apart from case-folding and tokenization. WER/CER use edit distance. Sentence BLEU is smoothed and averaged per utterance, so report the implementation and do not compare it as if it were sacreBLEU corpus BLEU. Character F-score is whitespace-normalized, beta=2, averaged per utterance. For a publication table, also report corpus-level sacreBLEU/chrF with their signatures; the included lightweight report is a screening/reproducibility tool, not a replacement for those standard corpus metrics.

## Data collection protocol

- Begin with 5 languages maximum, chosen by supervisor and available fluent annotators (recommended: English, Hindi, Hinglish, Bengali, Tamil). Add Telugu/Marathi only when comparable audio and annotation quality are available.
- Prepare at least 30 speakers and 100 utterances per language/condition as a pilot target; report the actual count, demographics only in aggregate, recording equipment, room noise, and exclusions. Do not claim representativeness from a convenience sample.
- Collect natural consented speech in quiet and noisy conditions; include both read prompts and spontaneous meeting speech. For Hinglish, stratify by code-switch frequency and preserve the spoken Roman/Devanagari convention in the reference policy.
- Have two fluent annotators transcribe/translate independently, reconcile disagreements, and keep an adjudication log. Blind annotators to system output. Keep speaker-disjoint train/dev/test splits if any prompt/model tuning is performed.
- Compare systems on identical input: production ASR+LLM translation, and a clearly named IndicTrans2 translation baseline fed the same source transcripts. This isolates translation quality. An additional end-to-end ASR+translation comparison must use the same original audio and be labeled as such.
- Freeze model identifiers, prompts, glossary, VAD settings, server region, hardware, network, concurrency, and date for each run. Run cold-start separately from warm repeated requests; do not mix provider rate-limit failures into latency percentiles. Record skipped/error counts.
- For latency, use monotonic timestamps and report speech-end-to-first-translated-words and speech-end-to-final-translation separately. Include VAD hangover and describe how speech end is annotated. Run enough repeated trials and report n, p50, p95, and failures per language/system.
- Compare energy VAD configurations on the same labeled audio first. Record missed speech, false activations, segmentation boundaries, and VAD decision delay in addition to downstream latency/quality. Only add a Silero/WebRTC implementation after selecting a compatible license/runtime and validating CPU cost on deployment hardware.

## Interpretation and limits

WER is lower-is-better; BLEU/chrF are higher-is-better. Translation metrics do not establish semantic correctness alone: add blinded bilingual human ratings for adequacy and fluency, and publish the rubric and inter-annotator agreement. Report per-language results, not only an aggregate. Include confidence intervals and the exact sample counts in the thesis tables. The current app still uses utterance-based Whisper ASR; the evaluator makes comparison possible but does not make the ASR streaming or prove a latency/quality improvement by itself.

## Milestones

1. Confirm title, language scope, consent and collection plan with supervisor before recording.
2. Build and adjudicate the small pilot corpus; verify JSONL IDs/references.
3. Establish frozen baseline scores and latency; then test VAD/settings or model changes one variable at a time.
4. Run paired evaluation, human review, error analysis, and repeat runs; archive manifests and machine-readable results.
5. Write the thesis with a transparent methods section, per-language tables, failure cases, limitations, and reproducibility appendix.
## Running the experiments

### Local IndicTrans2 baseline

The baseline runner uses AI4Bharat's documented Python `Model.batch_translate` interface and emits the same JSONL schema as the LinguaMeet evaluator. IndicTrans2 is an offline baseline, not the live-meeting default; install its dependencies and checkpoint in a separate environment from the app. Follow the official [IndicTrans2 inference and checkpoint instructions](https://github.com/AI4Bharat/IndicTrans2#inference).

Input example (`baseline-input.jsonl`):

```json
{"id":"en-hi-001","source_text":"Please send the meeting agenda tomorrow.","source_language":"en","target_language":"hi","reference":"कृपया कल बैठक का एजेंडा भेजें।"}
```

From `backend`, run `python -m scripts.indictrans2_predict baseline-input.jsonl --repo ..\\IndicTrans2 --checkpoint D:\\models\\indictrans2-en-hi --model-type ctranslate2 --device cpu --output indictrans2.jsonl`. For comparable results, concatenate the production-system and baseline outputs, then run `python -m scripts.evaluate paired-predictions.jsonl --require-paired --output results.json`. The runner supports English, Hindi, Bengali, Tamil, Telugu, and Marathi. Hinglish is deliberately excluded because IndicTrans2 has no Hinglish language code; report it as a separate condition and do not pass it off as Hindi.

### Energy-VAD sweep

Create a human-reviewed annotation file with speech intervals in milliseconds:

```json
{"segments":[{"start_ms":300,"end_ms":1100},{"start_ms":1800,"end_ms":2450}]}
```

Run `python -m scripts.vad_sweep recording-16k-mono.wav labels.json --hangovers 150,250,350,450 --min-rms 200,300,500 --output vad-results.json`. This executes every hangover/threshold pair on the same audio and reports interval F1, missed/false segments, boundary error, decision delay, CPU processing time, and real-time factor. A human-annotated, consented recording is required for meaningful accuracy claims; the generated voice sample is suitable only for a smoke test.

`Segment` now retains input sample offsets and the VAD decision offset so these measurements use the same timeline. These fields do not change the meeting event schema.
