import pytest


@pytest.fixture(autouse=True)
def no_real_gemini_calls(monkeypatch):
    """Los tests nunca llaman a Gemini de verdad, aunque .env tenga la clave."""
    monkeypatch.setenv("GEMINI_POLISH", "0")
