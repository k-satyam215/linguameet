import pytest

from app.evaluation import edit_distance, score_rows, sentence_bleu, sentence_chrf


def test_edit_distance_counts_substitution_and_insertions():
    assert edit_distance(["a", "b"], ["a", "c", "b"]) == 1
    assert edit_distance([], ["x"]) == 1


def test_translation_metrics_reward_exact_match():
    assert sentence_bleu("namaste duniya", "namaste duniya") > sentence_bleu("namaste duniya", "alvida duniya")
    assert sentence_chrf("नमस्ते दुनिया", "नमस्ते दुनिया") == pytest.approx(100)
    assert sentence_chrf("नमस्ते दुनिया", "अलविदा दुनिया") < 100


def test_score_rows_groups_languages_and_reports_percentile_latency():
    rows = [
        {
            "id": "a", "model": "groq", "task": "asr", "language": "hi",
            "reference": "kal aao", "hypothesis": "kal aao", "timings_ms": {"asr": 100},
        },
        {
            "id": "b", "model": "groq", "task": "translation", "language": "en",
            "reference": "come tomorrow", "hypothesis": "come tomorrow",
            "timings_ms": {"end_to_end": 500},
        },
    ]
    result = score_rows(rows)
    asr, translation = result["groups"]
    assert asr["wer"] == 0 and asr["cer"] == 0
    assert asr["latency_ms"]["asr"] == {"count": 1, "p50": 100, "p95": 100}
    assert translation["mean_sentence_chrf"] == pytest.approx(100)


def test_score_rows_rejects_duplicate_model_task_ids():
    row = {"id": "a", "model": "m", "task": "asr", "language": "hi", "reference": "a", "hypothesis": "a"}
    with pytest.raises(ValueError, match="duplicate"):
        score_rows([row, row])
