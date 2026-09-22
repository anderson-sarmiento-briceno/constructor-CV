import json
import os
import re
import time
from urllib import error, request

from dotenv import load_dotenv

load_dotenv()

_LAST_GEMINI_ERROR = ""


def _fallback_analysis(profile):
    keywords = []
    for skill in profile.get("habilidades", []):
        keywords.append(skill)

    summary = profile.get("perfil_profesional", {}).get("resumen", "")
    if not isinstance(summary, str) or len(summary.split()) < 45:
        summary = (
            "Ingeniero eléctrico con experiencia en infraestructura y redes MT/BT, gestión de proyectos, "
            "automatización, análisis de datos y eficiencia energética. Cuenta con experiencia reciente en "
            "movilidad eléctrica, modelos predictivos, pipelines ETL con Python, visualización en Power BI, "
            "chatbots y despliegue de soluciones de machine learning."
        )

    return {
        "cargo_detectado": "No validado automáticamente",
        "modelo": "local-fallback",
        "motivo": _LAST_GEMINI_ERROR or "Gemini no respondió",
        "palabras_clave": keywords[:20],
        "resumen_profesional": summary,
        "experiencia_priorizada": [
            "Green Mobil - Científico de Datos",
            "Enel Colombia - infraestructura y automatización",
            "Consultoría freelance - automatización energética",
        ],
        "logros_priorizados": [],
        "responsabilidades_priorizadas": [],
        "requisitos_no_evidenciados": [],
        "nivel_ajuste": "No determinado",
        "estado": "propuesta de análisis local",
    }


def _call_gemini(
    prompt,
    model_name="gemini-3.6-flash",
    max_retries=3,
    initial_delay=35,
):
    global _LAST_GEMINI_ERROR
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _LAST_GEMINI_ERROR = "GEMINI_API_KEY no está configurada"
        return None

    # Si hay una variable de entorno definida, tiene prioridad
    model_name = os.getenv("GEMINI_MODEL", model_name)

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(max_retries + 1):
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=60) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                text = parsed["candidates"][0]["content"]["parts"][0]["text"]
                result = json.loads(text)
                _LAST_GEMINI_ERROR = ""
                return result

        except error.HTTPError as exc:
            try:
                raw_error = exc.read().decode("utf-8", errors="replace")
                error_body = json.loads(raw_error)
                api_message = error_body.get("error", {}).get("message", "")
            except (ValueError, OSError):
                api_message = ""

            _LAST_GEMINI_ERROR = f"HTTP {exc.code}: {api_message}".strip()

            temporary_errors = {429, 500, 502, 503, 504}
            if exc.code in temporary_errors and attempt < max_retries:
                wait_time = None

                # 1. Intentar extraer tiempo exacto de espera desde el mensaje de Google
                match = re.search(
                    r"retry in (\d+(?:\.\d+)?)s", api_message, re.IGNORECASE
                )
                if match:
                    wait_time = float(match.group(1)) + 0.5

                # 2. Si no viene en el texto, buscar en los headers HTTP
                if not wait_time:
                    retry_after_header = exc.headers.get("Retry-After")
                    if retry_after_header and retry_after_header.isdigit():
                        wait_time = float(retry_after_header)

                # 3. Estrategia por defecto según tipo de error
                if not wait_time:
                    if exc.code == 429:
                        wait_time = initial_delay * (1.5**attempt)
                    else:
                        wait_time = 3.0 * (2**attempt)

                print(
                    f"⚠️ [{model_name}] Error HTTP {exc.code}. Reintentando en {wait_time:.1f}s... (Intento {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                continue

            return None

        except (error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            _LAST_GEMINI_ERROR = f"Error en la petición: {str(exc)}"
            return None

    return None


def analyze_offer_and_profile(offer_text, profile, model_name="gemini-3.6-flash"):
    """Usa Gemini solo para interpretar semánticamente la oferta y priorizar contenido.

    La verdad factual se toma del perfil maestro y el sistema siempre valida antes
    de aceptar cualquier afirmación factual.
    """
    if not offer_text or not isinstance(profile, dict):
        return _fallback_analysis(profile or {})

    profile_summary = json.dumps(profile, ensure_ascii=False)
    offer_sample = offer_text[:4000] if offer_text else ""

    prompt = f"""
    Eres un analista de selección con estricta regla anti-alucinación.
    Tu trabajo es analizar una oferta y un perfil profesional real.

    REGLAS:
    1. No inventes empleos, empresas, fechas, títulos, herramientas o métricas.
    2. Usa solo la información que recibe en el perfil y en la oferta.
    3. Si no hay evidencia suficiente, devuelve "NO_EVIDENCIADO".
    4. Devuelve SOLO JSON válido con estas claves:
       - cargo_detectado
       - palabras_clave
       - resumen_profesional
       - experiencia_priorizada
       - estado
       - nivel_ajuste (alto, medio, bajo o no determinado)
       - requisitos_no_evidenciados
       - logros_priorizados: textos copiados literalmente del perfil maestro
       - responsabilidades_priorizadas: textos copiados literalmente del perfil maestro

    PERFIL MAESTRO:
    {profile_summary}

    OFERTA:
    {offer_sample}

    El resumen_profesional debe tener entre 90 y 120 palabras, estar escrito en español
    profesional y explicar claramente: identidad profesional, años de experiencia,
    fortalezas que coinciden con la oferta, herramientas relevantes, sectores/proyectos
    relacionados y el tipo de valor que puede aportar. No hagas un resumen genérico ni
    repitas solamente palabras clave. Usa únicamente hechos comprobables del perfil maestro.
    Las palabras_clave deben ser términos de la oferta respaldados por el perfil maestro.
    experiencia_priorizada debe listar empresas/cargos reales, sin crear nombres nuevos.
    logros_priorizados y responsabilidades_priorizadas deben copiar literalmente textos
    existentes del perfil maestro, no reescribirlos ni inventar métricas.
    Responde únicamente con JSON válido.
    """

    gemini_response = _call_gemini(prompt, model_name=model_name)
    if gemini_response:
        generated_summary = str(gemini_response.get("resumen_profesional", "")).strip()
        if len(generated_summary.split()) < 70:
            generated_summary = ""
        cleaned = {
            "cargo_detectado": gemini_response.get("cargo_detectado", "NO_EVIDENCIADO"),
            "modelo": os.getenv("GEMINI_MODEL", model_name),
            "motivo": "Respuesta válida de Gemini",
            "palabras_clave": gemini_response.get("palabras_clave", [])[:30],
            "resumen_profesional": generated_summary,
            "experiencia_priorizada": gemini_response.get("experiencia_priorizada", []),
            "logros_priorizados": gemini_response.get("logros_priorizados", [])[:8],
            "responsabilidades_priorizadas": gemini_response.get("responsabilidades_priorizadas", [])[:8],
            "requisitos_no_evidenciados": gemini_response.get("requisitos_no_evidenciados", [])[:15],
            "nivel_ajuste": gemini_response.get("nivel_ajuste", "No determinado"),
            "estado": "analizado con Gemini",
        }
        return cleaned

    return _fallback_analysis(profile)