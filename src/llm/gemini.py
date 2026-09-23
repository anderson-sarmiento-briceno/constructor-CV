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


def _local_reorder_experience(experience, offer_text):
    """Reordena frases existentes por coincidencia con la oferta, sin inventar contenido."""
    description = str(experience.get("descripcion", "")).strip()
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", description) if item.strip()]
    offer_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", offer_text or "")
    }
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            -sum(word.casefold() in offer_words for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", item[1])),
            item[0],
        ),
    )
    return " ".join(sentence for _, sentence in ranked)


def _extract_role_from_offer(offer_text):
    role_patterns = (
        (r"cient[ií]fico\(?a\)?\s+de\s+datos", "Científico de Datos"),
        (r"data\s+scientist", "Data Scientist"),
        (r"analista\s+de\s+datos", "Analista de Datos"),
        (r"data\s+analyst", "Data Analyst"),
    )
    for pattern, role in role_patterns:
        if re.search(pattern, offer_text or "", flags=re.IGNORECASE):
            return role
    patterns = (
        r"(?:buscamos|vacante para|como)\s+(?:un\(?a\)?\s+)?([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ& ]{3,60})",
        r"(?:rol|cargo)\s+(?:de|para)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ& ]{3,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, offer_text or "", flags=re.IGNORECASE)
        if match:
            role = re.split(r"[.,!?:;\n]", match.group(1))[0].strip()
            role = re.sub(r"\s+", " ", role)
            if 2 <= len(role.split()) <= 8:
                return role
    return "NO_EVIDENCIADO"


def _local_offer_overview(offer_text, profile):
    text = (offer_text or "").casefold()
    role = _extract_role_from_offer(offer_text)
    if any(term in text for term in ("junior", "recién egresado", "bajo supervisión", "experiencia inicial")):
        level = "junior"
        priorities = ["análisis exploratorio", "preparación de datos", "documentación", "notebooks", "SQL", "Power BI", "Excel", "ETL"]
    elif any(term in text for term in ("analítica avanzada", "mlops", "machine learning", "inteligencia artificial", "modelos predictivos")):
        level = "avanzado"
        priorities = ["modelos predictivos", "Machine Learning", "producción", "pipelines", "Python", "SQL", "Power BI", "ETL", "MLOps"]
    else:
        level = "intermedio"
        priorities = ["análisis de datos", "automatización", "Python", "SQL", "Power BI", "ETL"]
    profile_text = json.dumps(profile, ensure_ascii=False).casefold()
    priorities = [item for item in priorities if item.casefold() in profile_text or item.casefold() in text]
    return {
        "cargo_detectado": role,
        "nivel_rol": level,
        "prioridades": priorities,
        "requisitos_no_evidenciados": [],
    }


def _fallback_analysis(profile):
    keywords = []
    for skill in profile.get("habilidades", []):
        keywords.append(skill)

    summary = profile.get("perfil_profesional", {}).get("resumen", "")
    if not isinstance(summary, str):
        summary = ""

    return {
        "cargo_detectado": "No validado automáticamente",
        "modelo": "local-fallback",
        "motivo": _LAST_OLLAMA_ERROR or "Ollama no respondió",
        "palabras_clave": keywords[:20],
        "resumen_profesional": summary,
        "experiencia_priorizada": [
            f"{item.get('empresa', '')} - {item.get('cargo', '')}"
            for item in profile.get("experiencia", [])
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
    max_retries=0,
    initial_delay=1,
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
        "keep_alive": "10m",
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
            timeout = int(os.getenv("OLLAMA_TIMEOUT", "75"))
            with request.urlopen(req, timeout=timeout) as response:
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
           "pasantía", "pasantia", "pasante", "internship", "práctica profesional", "practica profesional",
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
        len(description.split()) < 25
        or any(phrase in description.casefold() for phrase in evaluator_phrases)
        or any(company.casefold() in description.casefold() for company in forbidden_companies)
        or source_overlap < 3
    ):
        return _local_reorder_experience(experience, offer_text)
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
    """Prioriza habilidades y logros reales en una sola llamada local."""
    source = json.dumps({
        "aptitudes": profile.get("aptitudes", []),
        "software": profile.get("software", []),
        "competencias": profile.get("competencias", []),
        "habilidades_legacy": profile.get("habilidades", []),
        "certificaciones": profile.get("certificaciones", []),
        "logros": profile.get("logros", []),
    }, ensure_ascii=False)
    prompt = f"""
    Selecciona habilidades para un CV adaptado a una oferta laboral.
    Devuelve solo JSON con cuatro listas: aptitudes_clave, herramientas, competencias y logros.
    Usa exclusivamente elementos existentes en la categoría correspondiente de la fuente.
    No inventes ni reformules nombres. Elimina duplicados y ordena por relevancia para la oferta.
    aptitudes_clave debe contener máximo 7 elementos y herramientas máximo 12.
    competencias debe contener máximo 12 elementos.
    logros debe contener máximo 5 elementos copiados literalmente de la fuente.

    OFERTA:
    {offer_text[:4000]}

    FUENTE REAL:
    {source}
    """
    result = _text_response(prompt, model_name)
    return {
        "aptitudes_clave": result.get("aptitudes_clave", []),
        "herramientas": result.get("herramientas", []),
        "competencias": result.get("competencias", []),
        "logros": result.get("logros", []),
    }


def analyze_offer_and_profile(offer_text, profile, model_name="qwen2.5:7b"):
    """Analiza la oferta en bloques pequeños y combina resultados validados."""
    if not offer_text or not isinstance(profile, dict):
        return _fallback_analysis(profile or {})

    offer_sample = offer_text[:5000]
    profile_summary = json.dumps(profile, ensure_ascii=False)
    overview_prompt = f"""
    Analiza únicamente esta oferta laboral. Devuelve SOLO JSON con:
    cargo_detectado, nivel_rol (junior, intermedio, avanzado o no determinado),
    prioridades, requisitos_no_evidenciados.
    No describas experiencia del candidato y no inventes datos.

    OFERTA:
    {offer_sample}
    """
    overview = _text_response(overview_prompt, model_name)
    local_overview = _local_offer_overview(offer_text, profile)
    if not overview.get("cargo_detectado") or overview.get("cargo_detectado") == "NO_EVIDENCIADO":
        overview["cargo_detectado"] = local_overview["cargo_detectado"]
    if not overview.get("nivel_rol") or overview.get("nivel_rol") == "no determinado":
        overview["nivel_rol"] = local_overview["nivel_rol"]
    if not overview.get("prioridades"):
        overview["prioridades"] = local_overview["prioridades"]
    summary_prompt = f"""
    Redacta el perfil profesional de un CV para esta oferta.
    Devuelve SOLO JSON con resumen_profesional de 110 a 150 palabras.
    Escribe como CV propio, nunca como evaluación ni como explicación del proceso.
    No uses frases como "perfil maestro", "responsabilidades registradas", "según la
    oferta", "objetivos de la oferta" o "alineado con la oferta". Usa exclusivamente
    hechos del perfil maestro.
    No conviertas el sector o problema de la oferta en experiencia previa. Adapta el foco
    al nivel y prioridades entregados, pero no inventes empresas, cargos, sectores ni métricas.

    NIVEL Y PRIORIDADES:
    {json.dumps(overview, ensure_ascii=False)}

    PERFIL MAESTRO:
    {profile_summary}
    """
    summary_result = _text_response(summary_prompt, model_name)
    generated_summary = str(summary_result.get("resumen_profesional", "")).strip()
    if len(generated_summary.split()) < 60:
        generated_summary = ""

    active_model = os.getenv("OLLAMA_MODEL", model_name)
    detected_role = overview.get("cargo_detectado", "NO_EVIDENCIADO")
    if not detected_role or detected_role == "NO_EVIDENCIADO":
        detected_role = _extract_role_from_offer(offer_text)
    return {
        "cargo_detectado": detected_role,
        "modelo": f"ollama-{active_model}",
        "motivo": "Respuesta válida del modelo local Ollama",
        "palabras_clave": overview.get("prioridades", [])[:30],
        "resumen_profesional": generated_summary,
        "experiencia_priorizada": [],
        "logros_priorizados": [],
        "responsabilidades_priorizadas": [],
        "requisitos_no_evidenciados": overview.get("requisitos_no_evidenciados", [])[:15],
        "nivel_ajuste": overview.get("nivel_rol", "No determinado"),
        "estado": "analizado con modelo local (Ollama)",
    }