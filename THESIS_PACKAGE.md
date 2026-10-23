# LinguaMeet thesis package

This document assembles the research proposal, study protocol, reproducibility plan, and thesis outline around the current LinguaMeet prototype. It is ready for supervisor review. It deliberately does not report experimental findings: no consented, human-annotated speech corpus or locally runnable IndicTrans2 checkpoint is present in this checkout.

## Proposed title

**Evaluating Latency and Translation Quality in a Real-Time Multilingual Meeting Assistant for English, Hindi, and Hinglish**

Start with English, Hindi, and Hinglish, subject to supervisor approval and fluent annotator availability. Bengali and Tamil are optional extensions. Keep Hinglish as a separate code-switching condition; it is not an IndicTrans2 language code.

## Abstract draft (proposal stage)

Multilingual meetings can exclude participants who do not share a fluent spoken language. This project develops and evaluates LinguaMeet, a browser-based meeting prototype that combines video conferencing, utterance-based automatic speech recognition, translated captions, and optional translated speech. The study will examine how language direction and code-switching affect recognition and translation quality, how configurable energy-based voice activity detection affects segmentation, and how those choices relate to end-to-end latency. The planned pilot will compare the deployed recognition-and-translation pipeline with a local IndicTrans2 translation baseline on identical, human-checked utterances. Natural speech will be collected only after institutional approval and informed consent. The planned evaluation uses word and character error rates for recognition, corpus BLEU and chrF for translation, bilingual adequacy and fluency ratings, and speech-end-to-first-translation and speech-end-to-final-translation latency percentiles. VAD configurations will be compared on human-labelled speech intervals using interval precision, recall, F1, boundary error, decision delay, and processing time. The repository provides JSONL scoring, paired-output checks, IndicTrans2 prediction and VAD-sweep scripts, and a documented protocol. At this proposal stage, no participant dataset has been collected and no quality or latency improvement is claimed. The study will report per-language sample counts, failures, uncertainty, and limitations; results will be added only after the approved pilot is completed and independently checked.

## Research questions and hypotheses

1. **RQ1 — Recognition and translation:** How do ASR and translation quality vary by language direction and code-switching condition? Expect scores to vary by language/condition; Hinglish is reported separately because it is not a supported IndicTrans2 language label.
2. **RQ2 — Segmentation and latency:** How do energy-VAD hangover and threshold settings affect segmentation quality and end-to-end latency? A shorter hangover may reduce speech-end delay while increasing truncation risk. This is a hypothesis, not a result.
3. **RQ3 — Translation baseline:** On identical human-checked source transcripts, how does the production translation pipeline compare with IndicTrans2? This isolates translation from ASR. Audio-to-translation comparisons require both systems to process the same original audio and clear system boundaries.

## Study design

### Pilot scope

- Begin with English, Hindi, and Hinglish, subject to supervisor approval and annotator availability. Bengali and Tamil are optional extensions.
- Target at least 100 utterances per language/condition and 30 speakers if feasible. Record actual counts and treat this as a convenience pilot, not a representative sample.
- Include read prompts and spontaneous meeting-style speech, quiet and moderately noisy settings, and predeclared code-switch strata for Hinglish.
- Keep speaker-disjoint partitions if prompts, glossary, or system settings are tuned. Freeze a held-out evaluation partition before comparing systems.
- Have two fluent annotators independently prepare transcripts/translations, reconcile disagreements, and log adjudications. Annotators should not see system hypotheses before preparing references.

### Outcomes

| Area | Primary measures | Reporting unit |
| --- | --- | --- |
| ASR | WER, CER | Per language/condition, with numerator and denominator |
| Translation | Corpus sacreBLEU and chrF; blinded adequacy/fluency ratings | Per direction, with metric signatures and annotator agreement |
| Latency | Speech-end-to-first-translated-words; speech-end-to-final-translation; p50/p95 | Per system, language, cold/warm run, and sample count |
| VAD | Interval precision/recall/F1, missed/false intervals, boundary error, decision delay, CPU time, real-time factor | Per fixed hangover/threshold pair |
| Reliability | Timeouts, provider errors, empty output, dropped/retried utterances | Counts and rates; preserve failed IDs |

The repository's lightweight evaluator calculates edit-distance WER/CER and smoothed **mean sentence** BLEU/character F-score. Do not label these BLEU/chrF values as corpus sacreBLEU/chrF. The final thesis should use standard corpus-level metrics and blinded human review.

### Controlled variables

Record date, code commit, provider/model identifiers, prompt and glossary hashes, VAD settings, browser/OS, device, server region, network conditions, concurrency, run configuration when available, and whether a sample was cold or warm. Use monotonic timestamps. Report provider errors separately from successful-request latency percentiles.

## Data and ethics plan

1. Obtain supervisor and institutional approval and the applicable consent documents before recruiting or recording anyone.
2. Explain that speech is processed by the selected ASR/translation/TTS providers when those services are enabled. Review their current privacy terms with the institution before collection; do not upload identifiable recordings to an unapproved provider.
3. Use study IDs, store the identity key separately with restricted access, define retention/deletion dates, and keep raw recordings out of Git. Publish only de-identified material that consent and license permit.
4. Document language proficiency/annotation qualifications in aggregate only. Avoid unnecessary sensitive demographic information.
5. Preserve a data manifest and checksums without participant names, contact details, or raw audio in public artifacts.

**No consent letter is included.** The user identified the consent letter and supervisor as their remaining personal/institutional tasks. This package does not substitute for institutional approval or participant consent.

## Dataset and baseline status

- IN22-Conv is a published conversational machine-translation benchmark. Its Hugging Face dataset page currently requires a signed-in user to agree to share account information before accessing files. No agreement was accepted and no dataset was downloaded.
- The AI4Bharat IndicTrans2 distilled 200M model page also gates file access behind account/conditions acceptance. No account conditions were accepted and no checkpoint was downloaded.
- This repository therefore contains **evaluation tooling, not an executed IndicTrans2 benchmark**. Public benchmark results must not be described as LinguaMeet meeting-speech results.
- The generated Hindi WAV in `outputs/` is a demo asset, not participant data or a valid VAD evaluation corpus.

## Reproduction commands

From the repository root, install development requirements in an isolated Python environment, then:

```powershell
Set-Location backend
python -m pytest -q
python -m ruff check app tests scripts
```

Score an exported, paired system comparison:

```powershell
python -m scripts.evaluate paired-predictions.jsonl --require-paired --output metrics.json
```

Run the local IndicTrans2 adapter only after installing the upstream-compatible runtime and downloading a checkpoint through an account that has independently accepted its terms:

```powershell
python -m scripts.indictrans2_predict baseline-input.jsonl --repo ..\IndicTrans2 --checkpoint D:\models\indictrans2-en-hi --model-type ctranslate2 --device cpu --output indictrans2.jsonl
```

Run a VAD sweep only on 16 kHz mono PCM16 WAV and human-reviewed labels:

```powershell
python -m scripts.vad_sweep recording-16k-mono.wav annotations.json --hangovers 150,250,350,450 --min-rms 200,300,500 --output vad-results.json
```

For a complete frontend/backend local system check, follow the Windows quick-start and test instructions in `README.md`. The browser E2E suite uses mock AI and synthetic media; it verifies product wiring, not real-provider translation quality or physical-device audio behavior.

## Thesis writing outline

1. **Introduction:** accessibility problem, meeting translation context, objectives, research questions, contribution, scope.
2. **Related work:** multilingual NMT/IndicTrans2, ASR for Indian languages and code-switching, VAD, real-time translation latency, evaluation metrics. Cite primary papers and exact model/data versions.
3. **System:** architecture and event flow; language routing; VAD; provider boundaries; caption/TTS behavior; privacy-relevant data flow.
4. **Method:** approval/consent, participants, recording conditions, annotation policy, splits, baselines, frozen configuration, metrics, analysis plan.
5. **Results:** sample flow and exclusions, per-language ASR/MT/human scores, paired uncertainty, latency percentiles, VAD sweep, failures and qualitative errors. Populate only from archived runs.
6. **Discussion:** answers to each question, trade-offs, deployment implications, bias and generalization limits.
7. **Conclusion:** supported claims only, limitations, next study.
8. **Appendices:** annotation guide, prompt/version manifests, anonymized data schema, metric signatures, run instructions, institutional documents as permitted.

## Results table templates

### Translation / ASR

| System/version | Direction/condition | N | WER | CER | sacreBLEU (signature) | chrF (signature) | Adequacy/fluency | Failures |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| Pending approved pilot | — | — | — | — | — | — | — | — |

### Latency / VAD

| System/configuration | Language | N | First words p50/p95 ms | Final p50/p95 ms | VAD F1 | Boundary error ms | Decision delay ms | Failures |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| Pending approved pilot | — | — | — | — | — | — | — | — |

## Completion boundary

Repository implementation and reproducibility scaffolding are present. The non-consent-dependent written research plan is assembled here. Participant recording, human reference creation, provider/model benchmark runs, empirical result tables, and final thesis conclusions depend on supervisor/institutional approval and approved data access. No empirical result is asserted until those steps are complete.

## Primary references

- Gala et al., “IndicTrans2: Towards High-Quality and Accessible Machine Translation Models for all 22 Scheduled Indian Languages,” TMLR (2023): https://openreview.net/forum?id=vfT4YuzAYA
- AI4Bharat IndicTrans2 repository (inference, checkpoints, IN22 artifacts): https://github.com/AI4Bharat/IndicTrans2
- AI4Bharat IN22-Conv dataset card (scope, schema, access conditions): https://huggingface.co/datasets/ai4bharat/IN22-Conv
- AI4Bharat IndicTrans2 En-Indic distilled model card (model scope/access conditions): https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M

## Local verification on 2026-10-24

- Backend: 77 tests passed; Ruff passed.
- Frontend: 19 tests passed; TypeScript typecheck passed; production build passed.
- The real-browser E2E could not be run locally because Docker Desktop's LiveKit engine was not accessible from this session. The repository's E2E uses mock AI/synthetic devices and does not establish real-provider or physical-device speech quality.
- These checks verify implementation/build behavior; they do not replace the participant study or constitute thesis performance results.

## Production smoke verification on 2026-10-24

- The deployed Vercel lobby loaded and populated its multilingual language choices.
- A temporary production room was created. Two separate browser tabs joined it; both displayed `Video connected` and `Translation open`, and the English-speaking test participant showed `hear Hindi`.
- The in-app browser reported system denial for camera/microphone access. Both participants were disconnected after the check.
- This verifies production room creation, participant join, LiveKit connectivity, translation-WebSocket readiness, and language-direction configuration. It does **not** verify new speech recognition, translated captions, or translated audio playback in this run because no microphone audio was available.
- The earlier generated-audio production playback check remains documented in `outputs/client-demo-verification.md`; it used generated English speech and is not participant-data research.
