from corganshelper_service.transcribe import whisper_device


def test_the_default_is_the_first_cuda_device_in_float16(monkeypatch):
    monkeypatch.delenv("CORGANSHELPER_WHISPER", raising=False)
    assert whisper_device() == ("cuda", 0, "float16")


def test_a_device_index_can_be_chosen(monkeypatch):
    monkeypatch.setenv("CORGANSHELPER_WHISPER", "cuda:1")
    assert whisper_device() == ("cuda", 1, "float16")


def test_cpu_means_int8(monkeypatch):
    monkeypatch.setenv("CORGANSHELPER_WHISPER", "cpu")
    assert whisper_device() == ("cpu", 0, "int8")
