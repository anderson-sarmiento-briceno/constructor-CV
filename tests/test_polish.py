import io
import json
from email.message import Message
from urllib import error

import pytest

import src.llm.polish as polish

PROFILE = {
    "datos_personales": {"nombre": "Persona Prueba", "correo": "secreto@correo.com", "telefono": "+57 300 123 4567",
                         "profesion": "Ingeniero Eléctrico", "profesiones": ["Ingeniero Eléctrico", "Científico de Datos"]},
    "software": ["Python", "Power BI"],
    "experiencia": [{"empresa": "Green Mobil", "cargo": "Científico de Datos", "fechas": "2025",
                     "herramientas": ["Python", "Power BI"],
                     "descripcion": "Construí informes con telemetría, mejorando un 28% las proyecciones."}],
}
SUMMARY = "Soy Ingeniero Eléctrico y Científico de Datos. Desarrollo modelos predictivos con Python y tableros en Power BI."
EXPERIENCES = PROFILE["experiencia"]
NEW_SUMMARY = "Soy Ingeniero Eléctrico y Científico de Datos. Construyo modelos predictivos con Python y Power BI."
NEW_EXPERIENCE = "Automaticé informes de telemetría que mejoraron un 28% las proyecciones de consumo."


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _gemini_ok(payload):
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}}]}
    return _Response(json.dumps(body).encode())


def _gemini_error(code, message):
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
    return error.HTTPError(polish.GEMINI_URL, code, "error", Message(), body)


PROFILE_OK = lambda: _gemini_ok({"resumen": NEW_SUMMARY})  # noqa: E731
EXPERIENCES_OK = lambda: _gemini_ok({"experiencias": [{"indice": 0, "descripcion": NEW_EXPERIENCE}]})  # noqa: E731


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_POLISH", "1")
    monkeypatch.setenv("APY_KEY_GEMINI", "clave-uno-falsa")
    monkeypatch.setenv("APY_KEY_GEMINI_2", "clave-dos-falsa")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    state = {"requests": [], "responses": []}

    def urlopen(req, timeout):
        state["requests"].append(req)
        response = state["responses"].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(polish.request, "urlopen", urlopen)
    monkeypatch.setattr(polish.time, "sleep", lambda seconds: None)
    return state


def test_gemini_rewrites_profile_and_experiences_with_separate_prompts(gemini):
    gemini["responses"] = [PROFILE_OK(), EXPERIENCES_OK()]

    summary, descriptions, report = polish.polish_with_gemini(
        SUMMARY, EXPERIENCES, ["Python"], PROFILE, unevidenced=["Databricks"]
    )

    assert len(gemini["requests"]) == 2
    assert summary == NEW_SUMMARY and descriptions == [NEW_EXPERIENCE]
    assert report["estado"] == "aplicado"
    profile_request = json.loads(gemini["requests"][0].data)
    assert "PERFIL PROFESIONAL" in profile_request["systemInstruction"]["parts"][0]["text"]
    assert "Databricks" in profile_request["contents"][0]["parts"][0]["text"]  # requisitos no evidenciados
    sent = "".join(req.data.decode() for req in gemini["requests"])
    assert "secreto@correo.com" not in sent and "Persona Prueba" not in sent and "+57" not in sent
    assert "clave-uno-falsa" not in sent  # la clave va en la cabecera


def test_offer_words_missing_from_profile_are_sent_as_forbidden(gemini):
    gemini["responses"] = [PROFILE_OK(), EXPERIENCES_OK()]

    _, _, report = polish.polish_with_gemini(
        SUMMARY, EXPERIENCES, [], PROFILE, offer_text="Buscamos experto en Databricks y feature engineering con Python."
    )

    assert "databricks" in report["palabras_prohibidas"] and "python" not in report["palabras_prohibidas"]
    for req in gemini["requests"]:
        prompt = json.loads(req.data)["contents"][0]["parts"][0]["text"]
        assert "PALABRAS PROHIBIDAS" in prompt and "databricks" in prompt


def test_gemini_text_is_used_without_local_checks(gemini):
    # Aunque Gemini cambie el texto por completo, se usa: no hay control local.
    gemini["responses"] = [PROFILE_OK(), _gemini_ok({"experiencias": [{"indice": 0, "descripcion": "Texto distinto."}]})]

    _, descriptions, _ = polish.polish_with_gemini(SUMMARY, EXPERIENCES, [], PROFILE)

    assert descriptions == ["Texto distinto."]


def test_second_key_is_used_when_first_runs_out_of_quota(gemini):
    no_quota = _gemini_error(429, "You exceeded your current quota")
    gemini["responses"] = [no_quota, PROFILE_OK(), EXPERIENCES_OK()]

    summary, _, report = polish.polish_with_gemini(SUMMARY, EXPERIENCES, [], PROFILE)

    assert summary == NEW_SUMMARY
    assert report["perfil"] == f"{polish.DEFAULT_GEMINI_MODEL} con clave 2"  # mismo modelo, otra clave
    assert gemini["requests"][1].get_header("X-goog-api-key") == "clave-dos-falsa"
    assert all("clave-uno-falsa" not in notice for notice in report["avisos"])


def test_fallback_model_is_used_only_when_main_fails_with_every_key(gemini):
    overloaded = _gemini_error(503, "high demand")
    gemini["responses"] = [overloaded] * 8 + [PROFILE_OK(), EXPERIENCES_OK()]  # 4 intentos por clave

    _, _, report = polish.polish_with_gemini(SUMMARY, EXPERIENCES, [], PROFILE)

    assert report["perfil"] == f"{polish.DEFAULT_GEMINI_FALLBACK_MODEL} con clave 1"
    assert report["avisos"] == []  # funcionó con el respaldo: no es un aviso
    assert len(report["intentos_fallidos"]) == 2  # 3.6-flash con clave 1 y con clave 2
    assert polish.DEFAULT_GEMINI_MODEL == "gemini-3.6-flash"
    assert polish.DEFAULT_GEMINI_FALLBACK_MODEL == "gemini-3.5-flash-lite"


def test_groq_texts_are_kept_and_warned_when_gemini_is_unavailable(gemini):
    gemini["responses"] = [_gemini_error(429, "You exceeded your current quota")] * 8

    summary, descriptions, report = polish.polish_with_gemini(SUMMARY, EXPERIENCES, [], PROFILE)

    assert summary == SUMMARY and descriptions == [EXPERIENCES[0]["descripcion"]]
    assert report["estado"] == "no_disponible"
    assert any("Perfil: Gemini no disponible" in notice for notice in report["avisos"])
    assert any("Experiencias: Gemini no disponible" in notice for notice in report["avisos"])


def test_polish_is_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("GEMINI_POLISH", "0")
    summary, _, report = polish.polish_with_gemini(SUMMARY, EXPERIENCES, [], PROFILE)
    assert report["estado"] == "desactivado" and summary == SUMMARY
