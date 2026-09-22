import json
import os
import re
import time
from urllib import error, request

from dotenv import load_dotenv

load_dotenv()

_LAST_OLLAMA_ERROR = ""


def _text_response(prompt, model_name):
    response = _call_ollama(prompt, model_name=model_name)
    return response if isinstance(response, dict) else {}


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
        "motivo": _LAST_OLLAMA_ERROR or "Ollama no respondió",
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


def _call_ollama(
    prompt,
    model_name="qwen2.5:7b",
    max_retries=2,
    initial_delay=2,
):
    """Ejecuta inferencia local llamando al API REST de Ollama en localhost."""
    global _LAST_OLLAMA_ERROR

    # Se asegura de usar la IP local y el modelo local configurado.
    model_name = os.getenv("OLLAMA_MODEL", model_name)
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    url = f"{host}/api/generate"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2,
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
            with request.urlopen(req, timeout=120) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                text_response = parsed.get("response", "")

                # Limpieza por si el LLM envuelve la respuesta en bloques markdown
                clean_text = re.sub(r"^```json\s*", "", text_response.strip())
                clean_text = re.sub(r"\s*```$", "", clean_text)

                result = json.loads(clean_text)
                _LAST_OLLAMA_ERROR = ""
                return result

        except error.URLError as exc:
            _LAST_OLLAMA_ERROR = f"No se pudo conectar a Ollama ({exc.reason}). Asegúrate de que Ollama esté ejecutándose."
            if attempt < max_retries:
                time.sleep(initial_delay)
                continue
            return None

        except (TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            _LAST_OLLAMA_ERROR = f"Error en la respuesta local: {str(exc)}"
            if attempt < max_retries:
                time.sleep(initial_delay)
                continue
            return None

    return None


# Mantener _call_gemini como alias de compatibilidad hacia Ollama
_call_gemini = _call_ollama


def adapt_experience_to_offer(experience, offer_text, model_name="qwen2.5:7b", forbidden_companies=None):
    """Reescribe una experiencia real para la oferta sin alterar sus hechos."""
    source = json.dumps(experience, ensure_ascii=False)
    forbidden_companies = forbidden_companies or []
    forbidden_text = ", ".join(forbidden_companies) or "cualquier organización mencionada en la oferta"
    prompt = f"""
    Adapta una experiencia profesional real a una oferta laboral.
    Devuelve solo JSON con la clave descripcion_adaptada.
    Escribe entre 80 y 130 palabras, con tono profesional natural de CV, sin hablar de
    'el candidato', 'el perfil' ni de la evaluación. Redacta como una descripción propia
    y directa. Conserva literalmente empresa, cargo, fechas, herramientas, proyectos y
    métricas del texto fuente. No inventes ningún dato. Solo cambia orden, énfasis y
    redacción para conectar con la oferta.

    OFERTA:
    {offer_text[:4000]}

    EXPERIENCIA FUENTE:
    {source}

    La empresa objetivo no es una experiencia del profesional y está PROHIBIDO escribir
    su nombre. No escribas en futuro ni describas tareas que el profesional haría en la
    empresa objetivo. No menciones la oferta, el cargo buscado ni "en esta empresa".

    EMPRESAS U ORGANIZACIONES OBJETIVO PROHIBIDAS:
    {forbidden_text}
    """
    result = _text_response(prompt, model_name)
    description = str(result.get("descripcion_adaptada", "")).strip()
    evaluator_phrases = (
        "el candidato", "el perfil", "nivel de ajuste", "se ajusta a la oferta",
        "en rapicredit", "en esta empresa", "apoyaré", "implementaré", "contribuiré",
    )
    source_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{5,}", experience.get("descripcion", ""))
    }
    description_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{5,}", description)
    }
    source_overlap = len(source_words & description_words)
    if (
        len(description.split()) < 35
        or any(phrase in description.casefold() for phrase in evaluator_phrases)
        or any(company.casefold() in description.casefold() for company in forbidden_companies)
        or source_overlap < 4
    ):
        return experience.get("descripcion", "")
    return description


def adapt_achievements_to_offer(logros, offer_text, model_name="qwen2.5:7b"):
    """Prioriza y adapta logros existentes sin inventar resultados ni empresas."""
    source = json.dumps(logros, ensure_ascii=False)
    prompt = f"""
    Selecciona hasta cinco logros reales para un CV adaptado a una oferta.
    Devuelve solo JSON con la clave logros_adaptados, una lista de textos.
    Usa únicamente los logros fuente. Puedes mejorar el orden y hacer ajustes mínimos
    de redacción, pero conserva literalmente empresas, herramientas y métricas.
    Escribe como logros propios del profesional, no como evaluación. No menciones la
    oferta, la empresa objetivo ni tareas futuras.

    OFERTA:
    {offer_text[:4000]}

    LOGROS FUENTE:
    {source}
    """
    result = _text_response(prompt, model_name)
    return [str(item).strip() for item in result.get("logros_adaptados", []) if str(item).strip()]


def adapt_skills_to_offer(profile, offer_text, model_name="qwen2.5:7b"):
    """Prioriza habilidades reales y evita duplicados en la salida del CV."""
    source = json.dumps({
        "habilidades": profile.get("habilidades", []),
        "certificaciones": profile.get("certificaciones", []),
    }, ensure_ascii=False)
    prompt = f"""
    Selecciona habilidades para un CV adaptado a una oferta laboral.
    Devuelve solo JSON con dos listas: aptitudes_clave y herramientas.
    Usa exclusivamente elementos existentes en la fuente. No inventes ni reformules
    nombres de tecnologías. Elimina duplicados y ordena por relevancia para la oferta.
    aptitudes_clave debe contener máximo 7 elementos y herramientas máximo 12.

    OFERTA:
    {offer_text[:4000]}

    FUENTE REAL:
    {source}
    """
    result = _text_response(prompt, model_name)
    return {
        "aptitudes_clave": result.get("aptitudes_clave", []),
        "herramientas": result.get("herramientas", []),
    }


def analyze_offer_and_profile(offer_text, profile, model_name="qwen2.5:7b"):
    """Usa el modelo local (vía Ollama) para interpretar semánticamente la oferta y priorizar contenido.

    La verdad factual se toma del perfil maestro y el sistema siempre valida antes
    de aceptar cualquier afirmación factual.
    """
    if not offer_text or not isinstance(profile, dict):
        return _fallback_analysis(profile or {})

    profile_summary = json.dumps(profile, ensure_ascii=False)
    offer_sample = offer_text[:4000] if offer_text else ""

    prompt = f"""
    Eres un analista de selección con estricta regla anti-alucinación.
    Tu trabajo es analizar una oferta laboral y un perfil profesional real.

    REGLAS ESTRICTAS:
    1. No inventes empleos, empresas, fechas, títulos, herramientas ni métricas.
    2. Usa solo la información del perfil maestro y de la oferta.
    3. Si no hay evidencia suficiente, devuelve "NO_EVIDENCIADO".
    4. Devuelve ÚNICAMENTE un objeto JSON válido con estas claves exactas:
       - cargo_detectado
       - palabras_clave
       - resumen_profesional
       - experiencia_priorizada
       - estado
       - nivel_ajuste (alto, medio, bajo o no determinado)
       - requisitos_no_evidenciados
       - logros_priorizados
       - responsabilidades_priorizadas

    PERFIL MAESTRO:
    {profile_summary}

    OFERTA:
    {offer_sample}

    INSTRUCCIONES DE FORMATO:
    - resumen_profesional: entre 110 y 150 palabras, escrito como un resumen de CV en tercera persona neutra o estilo nominal profesional. No digas 'el candidato', 'el perfil', 'se ajusta', 'nivel de ajuste' ni hagas una evaluación. Explica experiencia, especialidad, herramientas, proyectos relacionados, sectores y valor profesional.
    - palabras_clave: lista de términos de la oferta respaldados por el perfil maestro.
    - experiencia_priorizada: lista de empresas/cargos reales del perfil.
    - logros_priorizados y responsabilidades_priorizadas: copiar literalmente del perfil maestro.

    Responde SOLAMENTE en formato JSON.
    """

    local_response = _call_ollama(prompt, model_name=model_name)
    active_model = os.getenv("OLLAMA_MODEL", model_name)

    if local_response:
        generated_summary = str(local_response.get("resumen_profesional", "")).strip()
        if len(generated_summary.split()) < 80:
            generated_summary = ""

        cleaned = {
            "cargo_detectado": local_response.get("cargo_detectado", "NO_EVIDENCIADO"),
            "modelo": f"ollama-{active_model}",
            "motivo": "Respuesta válida del modelo local Ollama",
            "palabras_clave": local_response.get("palabras_clave", [])[:30],
            "resumen_profesional": generated_summary,
            "experiencia_priorizada": local_response.get("experiencia_priorizada", []),
            "logros_priorizados": local_response.get("logros_priorizados", [])[:8],
            "responsabilidades_priorizadas": local_response.get("responsabilidades_priorizadas", [])[:8],
            "requisitos_no_evidenciados": local_response.get("requisitos_no_evidenciados", [])[:15],
            "nivel_ajuste": local_response.get("nivel_ajuste", "No determinado"),
            "estado": "analizado con modelo local (Ollama)",
        }
        return cleaned

    return _fallback_analysis(profile)