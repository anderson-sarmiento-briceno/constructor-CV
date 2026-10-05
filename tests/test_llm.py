import io
import json
from email.message import Message
from urllib import error

import pytest

import src.llm.client as client
import src.llm.llm as llm

PROFILE = {
    "datos_personales": {
        "nombre": "Persona Prueba",
        "profesion": "Ingeniero Eléctrico",
        "profesiones": ["Ingeniero Eléctrico", "Científico de Datos"],
        "ciudad": "Ciudad Secreta",
        "telefono": "+57 300 123 4567",
        "correo": "secreto@correo.com",
        "linkedin": "linkedin.com/in/secreto",
        "github": "github.com/secreto",
        "foto": "foto_secreta.png",
    },
    "perfil_profesional": {"resumen": "Ingeniero eléctrico con análisis de datos."},
    "experiencia": [
        {
            "empresa": "Green Mobil", "cargo": "Científico de Datos", "fechas": "Jul 2025 – Sep 2025",
            "sectores": ["movilidad eléctrica"],
            "descripcion": "Desarrollé modelos predictivos de desgaste de flota con Python y construí procesos ETL "
                           "para consolidar telemetría y consumo energético en tableros de Power BI.",
        },
    ],
    "software": ["Python", "Power BI", "SQL"],
    "competencias": ["ETL", "Modelos predictivos"],
}
OFFER = "Buscamos Científico de Datos con Python, SQL y Databricks para el sector bancario."
VALID_SUMMARY = (
    "Soy Ingeniero Eléctrico y Científico de Datos con experiencia en análisis de datos. "
    "He desarrollado modelos predictivos con Python para anticipar el desgaste de una flota eléctrica. "
    "También he construido procesos ETL que consolidan telemetría en tableros de Power BI. "
    "Mi experiencia combina ingeniería eléctrica, análisis de información y automatización de reportes. "
    "Trabajo con foco en la calidad de los datos, la documentación técnica y la mejora continua de procesos operativos."
)


@pytest.fixture
def fake_chat(monkeypatch):
    """Sustituye la llamada a Groq; responde en orden con la lista `responses`."""
    state = {"prompts": [], "responses": []}

    def chat(system, user, json_mode=True, max_retries=3):
        state["prompts"].append(system + "\n" + user)
        response = state["responses"].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(llm, "chat", chat)
    return state


# --- Cliente Groq -----------------------------------------------------------

class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _ok(content):
    return _Response(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def _http_error(code, retry_after=None, message="error"):
    headers = Message()
    if retry_after:
        headers["retry-after"] = retry_after
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
    return error.HTTPError(client.GROQ_URL, code, "error", headers, body)


@pytest.fixture
def fake_urlopen(monkeypatch):
    monkeypatch.setenv("APY_KEY", "sk-clave-falsa-123")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    state = {"requests": [], "responses": [], "sleeps": []}

    def urlopen(req, timeout):
        state["requests"].append(req)
        response = state["responses"].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client.request, "urlopen", urlopen)
    monkeypatch.setattr(client.time, "sleep", state["sleeps"].append)
    return state


def test_client_sends_json_mode_and_default_model(fake_urlopen):
    fake_urlopen["responses"] = [_ok('{"a": 1}')]

    assert client.chat("reglas", "tarea") == {"a": 1}
    body = json.loads(fake_urlopen["requests"][0].data)
    assert body["model"] == client.DEFAULT_MODEL
    assert body["temperature"] == 0.2
    assert body["response_format"] == {"type": "json_object"}


def test_client_retries_429_and_5xx_using_retry_after(fake_urlopen):
    fake_urlopen["responses"] = [_http_error(429, retry_after="3"), _http_error(503), _ok('{"b": 2}')]

    assert client.chat("reglas", "tarea") == {"b": 2}
    assert fake_urlopen["sleeps"] == [3.0, 2.0]


def test_client_retries_when_model_fails_to_generate_json(fake_urlopen):
    fake_urlopen["responses"] = [
        _http_error(400, message="Failed to generate JSON. Please adjust your prompt."),
        _ok('{"c": 3}'),
    ]

    assert client.chat("reglas", "tarea") == {"c": 3}


def test_client_does_not_retry_other_400_errors(fake_urlopen):
    fake_urlopen["responses"] = [_http_error(400, message="model not found")]

    with pytest.raises(client.LLMError):
        client.chat("reglas", "tarea")
    assert len(fake_urlopen["requests"]) == 1


def test_client_error_message_never_contains_the_key(fake_urlopen):
    fake_urlopen["responses"] = [_http_error(401, message="Invalid API Key")]

    with pytest.raises(client.LLMError) as exc:
        client.chat("reglas", "tarea")
    assert "401" in str(exc.value)
    assert "sk-clave-falsa-123" not in str(exc.value)


def test_client_model_comes_from_env(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "otro/modelo")
    assert client.model_name() == "otro/modelo"


# --- Prompts y validación -----------------------------------------------------

def test_local_role_extraction_ignores_lowercase_phrases():
    offer = "Promover la analítica avanzada e inteligencia artificial como habilitadores de la estrategia."
    assert llm._extract_role_from_offer(offer) == "NO_EVIDENCIADO"
    assert llm._extract_role_from_offer("buscamos Analista de Riesgo.") == "Analista de Riesgo"


def test_prompts_never_send_personal_data(fake_chat):
    fake_chat["responses"] = [{}, {}]

    llm.analyze_offer_and_profile(OFFER, PROFILE)
    llm.adapt_experiences_and_skills(PROFILE, PROFILE["experiencia"], OFFER)

    sent = "\n".join(fake_chat["prompts"])
    for key in ("nombre", "ciudad", "telefono", "correo", "linkedin", "github", "foto"):
        assert PROFILE["datos_personales"][key] not in sent
    assert "Científico de Datos" in sent  # profesiones sí viaja


def test_summary_retry_does_not_resend_offer(fake_chat):
    fake_chat["responses"] = [
        {"cargo_detectado": "Científico de Datos", "prioridades": ["Python", "SQL"],
         "resumen_profesional": "Experto en Databricks y banca."},
        {"resumen_profesional": VALID_SUMMARY},
    ]

    analysis = llm.analyze_offer_and_profile(OFFER, PROFILE)

    assert analysis["resumen_origen"] == "llm_reintento"
    assert [attempt["valido"] for attempt in analysis["resumen_intentos"]] == [False, True]
    assert OFFER not in fake_chat["prompts"][1]


def test_api_failure_uses_local_fallback_without_retry(fake_chat):
    fake_chat["responses"] = [llm.LLMError("Groq respondió HTTP 429")]

    analysis = llm.analyze_offer_and_profile(OFFER, PROFILE)

    assert len(fake_chat["prompts"]) == 1
    assert analysis["resumen_origen"] == "fallback_local"
    assert analysis["resumen_intentos"][0]["motivos_rechazo"] == ["Groq respondió HTTP 429"]


INVENTED_EXPERIENCE = (
    "Lideré proyectos de Databricks en el sector bancario para modelos de riesgo, "
    "desarrollando pipelines en Databricks y reportes regulatorios para la banca."
)
FIXED_EXPERIENCE = (
    "Desarrollé modelos predictivos de desgaste de flota con Python y construí procesos ETL "
    "para consolidar telemetría y consumo energético en tableros de Power BI, con datos "
    "ordenados para el seguimiento de la operación y de los modelos predictivos de la flota."
)


def test_invented_experience_falls_back_to_original_text(fake_chat):
    experience = PROFILE["experiencia"][0]
    fake_chat["responses"] = [
        {"experiencias": [{"indice": 0, "descripcion_adaptada": INVENTED_EXPERIENCE}], "herramientas": ["Python"]},
        {"descripcion_adaptada": INVENTED_EXPERIENCE},
    ]

    result = llm.adapt_experiences_and_skills(PROFILE, [experience], OFFER, ["Banco Ejemplo"])

    assert len(fake_chat["prompts"]) == 2
    assert result["descripciones"] == [experience["descripcion"]]
    assert result["diagnosticos"][0]["origen"] == "fallback_local"
    assert result["diagnosticos"][0]["intentos"] == 2
    assert any("databricks" in reason for reason in result["diagnosticos"][0]["motivo_fallback"])
    assert result["habilidades"]["herramientas"] == ["Python"]


def test_rejected_experience_retry_sends_forbidden_words_without_offer(fake_chat):
    experience = PROFILE["experiencia"][0]
    fake_chat["responses"] = [
        {"experiencias": [{"indice": 0, "descripcion_adaptada": INVENTED_EXPERIENCE}]},
        {"descripcion_adaptada": FIXED_EXPERIENCE},
    ]

    result = llm.adapt_experiences_and_skills(PROFILE, [experience], OFFER)

    retry_prompt = fake_chat["prompts"][1]
    assert "PALABRAS PROHIBIDAS" in retry_prompt and "databricks" in retry_prompt
    assert OFFER not in retry_prompt
    assert result["descripciones"] == [FIXED_EXPERIENCE]
    assert result["diagnosticos"][0]["origen"] == "llm_reintento"


def test_experience_with_numbers_not_in_source_is_rejected():
    experience = PROFILE["experiencia"][0]
    issues = llm._experience_issues(FIXED_EXPERIENCE + " Reduje los costos en un 45%.", experience, OFFER, [])
    assert any("cifras" in issue and "45" in issue for issue in issues)


def test_summary_with_percentages_is_rejected():
    issues = llm._summary_validation_issues(VALID_SUMMARY + " Mejoré la precisión en un 28%.", PROFILE, OFFER)
    assert any("porcentajes" in issue for issue in issues)


def test_model_text_is_normalized_for_pdf(fake_chat):
    fake_chat["responses"] = [{"resumen_profesional": "Uso Scikit‑learn y Python; subió un 35 %."}]
    assert llm._ask("tarea") == {"resumen_profesional": "Uso Scikit-learn y Python; subió un 35%."}


def test_summary_with_more_than_one_y_per_sentence_is_rejected():
    bad = VALID_SUMMARY + " Construyo y valido modelos predictivos y de regresión en energía y movilidad."
    issues = llm._summary_validation_issues(bad, PROFILE, OFFER)
    assert any('más de una "y"' in issue for issue in issues)


def test_summary_rejects_single_unevidenced_offer_term_and_cliches():
    bad = VALID_SUMMARY + " Uso Databricks para tomar decisiones estratégicas."
    issues = llm._summary_validation_issues(bad, PROFILE, OFFER)
    assert any("databricks" in issue for issue in issues)
    assert any("muletillas" in issue for issue in issues)


def test_offer_terms_used_anywhere_in_profile_are_allowed_in_experiences():
    experience = PROFILE["experiencia"][0]
    profile = {**PROFILE, "competencias": ["Procesamiento mediante Spark"]}
    offer = "Generar valor mediante analítica con Databricks."
    text = FIXED_EXPERIENCE + " Integré los datos mediante procesos automáticos."

    assert not any("términos" in issue for issue in llm._experience_issues(text, experience, offer, [], profile))
    issues = llm._experience_issues(text + " Usé Databricks.", experience, offer, [], profile)
    assert any("databricks" in issue for issue in issues)


def test_offer_wording_is_style_but_offer_requirements_are_rejected():
    offer = "Comunicar hallazgos a líderes. Requisito: Databricks."
    requirements = ["Databricks", "Comunicación de resultados"]
    text = VALID_SUMMARY + " Comunico hallazgos con claridad."

    hard = llm._summary_validation_issues(text, PROFILE, offer, include_style=False, requirements=requirements)
    style = llm._summary_validation_issues(text, PROFILE, offer, requirements=requirements)
    assert not hard
    assert any("vocabulario" in issue and "hallazgos" in issue for issue in style)

    claimed = llm._summary_validation_issues(text + " Uso Databricks.", PROFILE, offer,
                                             include_style=False, requirements=requirements)
    assert any("databricks" in issue for issue in claimed)
    # Sin lista de requisitos (análisis fallido) todo término sin respaldo rechaza.
    assert llm._summary_validation_issues(text, PROFILE, offer, include_style=False)


def test_overclaims_are_rejected_unless_source_says_so():
    source = {"descripcion": "Generé el insumo técnico para la certificación ISO 50001."}
    assert llm._overclaim_issues("Mis modelos permitieron la certificación ISO 50001.", source)
    assert llm._overclaim_issues("Lideré la automatización de informes.", source)
    assert not llm._overclaim_issues("Lideré equipos.", {"descripcion": "Lideré equipos de obra."})


def test_summary_with_only_style_issues_is_kept_after_retry(fake_chat):
    styled = VALID_SUMMARY + " Construyo modelos y tableros con Python y Power BI."
    fake_chat["responses"] = [{"resumen_profesional": styled}, {"resumen_profesional": styled}]

    analysis = llm.analyze_offer_and_profile(OFFER, PROFILE)

    assert analysis["resumen_origen"] == "llm_reintento"
    assert analysis["resumen_profesional"] == styled
    assert "TEXTO RECHAZADO" in fake_chat["prompts"][1]
    assert analysis["resumen_intentos"][1]["advertencias_estilo"]


def test_accepted_experiences_make_no_retry(fake_chat):
    experience = PROFILE["experiencia"][0]
    fake_chat["responses"] = [{"experiencias": [{"indice": 0, "descripcion_adaptada": FIXED_EXPERIENCE}]}]

    result = llm.adapt_experiences_and_skills(PROFILE, [experience], OFFER)

    assert len(fake_chat["prompts"]) == 1
    assert result["diagnosticos"][0]["origen"] == "llm"
