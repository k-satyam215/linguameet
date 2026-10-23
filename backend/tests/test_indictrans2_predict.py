from scripts.indictrans2_predict import predict_rows


class FakeIndicTrans2:
    def __init__(self):
        self.calls = []

    def batch_translate(self, texts, source, target):
        self.calls.append((texts, source, target))
        return ["नमस्ते"]


def test_predict_rows_preserves_pairing_and_measures_model_latency():
    model = FakeIndicTrans2()
    rows = [{
        "id": "en-hi-1", "source_text": "hello", "source_language": "en",
        "target_language": "hi", "reference": "नमस्ते",
    }]
    result = predict_rows(rows, model)
    assert result[0]["id"] == "en-hi-1"
    assert result[0]["model"] == "indictrans2-ct2"
    assert result[0]["hypothesis"] == "नमस्ते"
    assert result[0]["language"] == "hi"
    assert result[0]["timings_ms"]["translation_model"] >= 0
    assert model.calls == [(["hello"], "eng_Latn", "hin_Deva")]
