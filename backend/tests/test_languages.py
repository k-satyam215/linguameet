from app.languages import DEFAULT_REGISTRY as R


def test_core_languages_present():
    for code in ("en", "hi", "hi-en"):
        assert R.get(code) is not None


def test_hinglish_has_asr_prompt_and_translation_note():
    h = R.require("hi-en")
    assert h.asr_prompt
    assert "Kal deployment hai" not in h.asr_prompt
    assert "Hinglish" in h.note
    assert h.base == "hi"


def test_same_language_treats_hindi_and_hinglish_as_same():
    assert R.same_language("hi", "hi-en")
    assert not R.same_language("hi", "en")


def test_from_name_maps_whisper_names():
    assert R.from_name("english").code == "en"
    assert R.from_name("Hindi").code == "hi"
    assert R.from_name("klingon") is None


def test_unknown_language_is_rejected():
    assert not R.can_listen("xx")
    assert not R.can_speak("xx")
    import pytest

    with pytest.raises(KeyError):
        R.require("xx")
