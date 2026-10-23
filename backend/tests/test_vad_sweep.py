from scripts.vad_sweep import score_intervals


def test_vad_sweep_reports_misses_false_activations_and_decision_delay():
    predicted = [(100 * 16, 900 * 16, 1050 * 16), (2000 * 16, 2200 * 16, 2300 * 16)]
    reference = [(300 * 16, 1000 * 16)]
    result = score_intervals(predicted, reference)
    assert result["matched_segments"] == 1
    assert result["false_activations"] == 1
    assert result["missed_segments"] == 0
    assert result["mean_decision_delay_ms"] == 50
