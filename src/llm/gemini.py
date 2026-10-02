import json
import os
import re
import time
from urllib import error, request
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

_LAST_OLLAMA_ERROR = ""

_STOPWORDS_ES = {
    "para", "con", "los", "las", "una", "uno", "del", "que", "por", "como", "sobre",
    "entre", "desde", "hacia", "sus", "este", "esta", "estos", "estas", "sea", "ser",
    "más", "debe", "deben", "tiene", "tienen", "será", "serán", "años", "nivel", "rol",
    "cargo", "empresa", "oferta", "puesto", "vacante", "requisitos", "requisito",
    "conocimientos", "conocimiento", "experiencia", "trabajo", "equipo", "equipos",
    "proyectos", "proyecto", "buscamos", "candidato", "candidata", "perfil",
    "habilidades", "habilidad", "capacidad", "capacidades", "área", "areas", "gestión",
    "responsable", "funciones", "función", "objetivo", "objetivos", "resultados",
    "manejo", "conocer", "excelente", "deseable", "indispensable", "importante",
    "mínimo", "salario", "modalidad", "horario", "beneficios", "ofrecemos",
}


def _significant_terms(text):
    """Palabras/siglas de 3+ letras relevantes, ignorando conectores comunes."""
    words = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", text or "")
    return {word.casefold() for word in words if word.casefold() not in _STOPWORDS_ES}


def _unevidenced_offer_terms(generated_text, offer_text, source_fact):
    """Firewall genérico: términos que están en la oferta y en el texto generado,
    pero no en la fuente real (experiencia), sin importar de qué dominio se trate."""
    source_text = json.dumps(source_fact, ensure_ascii=False).casefold()
    offer_terms = _significant_terms(offer_text)
    generated_terms = _significant_terms(generated_text)
    candidate_terms = offer_terms & generated_terms
    return {
        term for term in candidate_terms
        if not re.search(r"\b" + re.escape(term) + r"\b", source_text)
    }


def _summary_validation_issues(summary, profile, offer_text):
    issues = []
    summary_text = str(summary or "")
    if len(summary_text.split()) < 60:
        issues.append("resumen menor de 60 palabras o vacío")

    summary_lower = summary_text.casefold()
    profile_text = json.dumps(profile, ensure_ascii=False).casefold()

    if not any(term in summary_lower for term in ("soy ", "tengo ", "he ", "mi experiencia", "mi formación")):
        issues.append("no cumple primera persona")
    if any(term in summary_lower for term in (
        "el candidato", "el profesional", "su trayectoria", "según la oferta",
        "perfil maestro", "responsabilidades registradas", "objetivos de la oferta",
        "objetivos del rol", "alineadas con la oferta", "para el puesto de",
        "ajustado al perfil", "alinea con los requisitos", "como se solicita",
        "mi perfil se adapta",
    )):
        issues.append("contiene frases meta o tercera persona")

    offer_terms = {term for term in _significant_terms(offer_text) if len(term) >= 4}
    summary_terms = _significant_terms(summary)
    invented = [
        term for term in (offer_terms & summary_terms)
        if not re.search(r"\b" + re.escape(term) + r"\b", profile_text)
    ]
    if len(invented) >= 2:
        issues.append("incluye términos de oferta sin evidencia: " + ", ".join(sorted(invented)))
    return issues


def summary_is_factual(summary, profile, offer_text):
    """Valida primera persona y rechaza varias afirmaciones sin respaldo literal."""
    return not _summary_validation_issues(summary, profile, offer_text)



# ===========================================================================
# BLOQUE DE REEMPLAZO PARA src/llm/gemini.py
#
# Reemplaza todo lo que va desde el encabezado
#   "# 1. DETECTOR Y LIMPIADOR DINÁMICO DE REPETICIONES"
# hasta el final de polish_text_with_ollama (justo antes de `def _text_response`).
# Además, agrega `import ast` junto a los otros imports al inicio del archivo.
# ===========================================================================

# ---------------------------------------------------------------------------
# Ajustes del pulido
# ---------------------------------------------------------------------------
_POLISH_MIN_RATIO = 0.70   # el texto pulido no puede ser menor al 70% del original
_POLISH_MAX_RATIO = 1.30   # ni mayor al 130%
_POLISH_TEXT_KEYS = (
    "texto", "texto_reescrito", "reescrito", "resumen", "resumen_profesional",
    "resultado", "response", "text", "output",
)
_POLISH_META_PHRASES = (
    "el candidato", "el profesional", "su trayectoria", "según la oferta",
    "perfil maestro", "objetivos de la oferta", "para el puesto de",
)
_FIRST_PERSON_START = re.compile(r"^\s*(soy|tengo|he|mi|cuento|poseo)\b", re.IGNORECASE)

# Diagnóstico del último pulido (para imprimirlo o guardarlo si quieres depurar)
_LAST_POLISH_REPORT = {}


# ===========================================================================
# 1. UTILIDADES DE TEXTO
# ===========================================================================

def _get_frequent_words(text: str, top_n: int = 3, min_length: int = 4) -> list:
    """Palabras con significado que se repiten 3 o más veces en el texto."""
    stopwords = {
        "de", "del", "en", "con", "el", "la", "los", "las", "para", "por",
        "un", "una", "que", "como", "sus", "mas", "su", "sobre",
        "este", "esta", "estos", "estas", "entre", "hasta", "desde"
    }
    words = [w.lower().strip(".,;:-()") for w in text.split()]
    filtered = [w for w in words if len(w) >= min_length and w not in stopwords]
    counts = Counter(filtered)
    return [word for word, count in counts.items() if count >= 3]


def _fix_grammar_and_punctuation(texto: str) -> str:
    """Limpia comas, espacios dobles y conectores sueltos.

    Ya NO baja a minúscula la letra que sigue a una coma: esa regla dañaba
    nombres de tecnologías y conceptos ("Ingeniería de Datos" -> "ingeniería de Datos").
    """
    if not texto:
        return texto
    t = texto
    t = re.sub(r"\b(de|en|con|para|por|y|o)\s*,", ",", t, flags=re.IGNORECASE)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"\s+([,.])", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _extract_text_from_llm(result):
    """Devuelve SOLO el texto de una respuesta del modelo.

    Maneja: str, dict (con cualquier clave), listas, dicts anidados y dicts que
    llegaron convertidos a texto, por ejemplo "{'reescrito': '...'}".
    """
    if result is None:
        return ""
    if isinstance(result, str):
        text = result.strip()
        if text and text[0] in "{[":
            parsed = None
            try:
                parsed = json.loads(text)
            except ValueError:
                try:
                    parsed = ast.literal_eval(text)
                except (ValueError, SyntaxError):
                    parsed = None
            if isinstance(parsed, (dict, list, tuple)):
                return _extract_text_from_llm(parsed)
            if isinstance(parsed, str):
                return parsed.strip()
        return text
    if isinstance(result, dict):
        for key in _POLISH_TEXT_KEYS:
            value = result.get(key)
            if value:
                extracted = _extract_text_from_llm(value)
                if extracted:
                    return extracted
        candidates = [_extract_text_from_llm(value) for value in result.values()]
        candidates = [item for item in candidates if item]
        return max(candidates, key=len) if candidates else ""
    if isinstance(result, (list, tuple)):
        parts = [_extract_text_from_llm(item) for item in result]
        return " ".join(part for part in parts if part).strip()
    return str(result).strip()


def _polish_rejection_reasons(original, polished, frequent_before, profile=None, offer_text=""):
    """Lista de motivos por los que NO se acepta el texto pulido (vacía = aceptado)."""
    if not polished:
        return ["respuesta vacía"]

    reasons = []
    if re.search(r"[{}\[\]]", polished):
        reasons.append("contiene llaves o corchetes: no es texto limpio")

    orig_words = len(original.split())
    pol_words = len(polished.split())
    if pol_words < orig_words * _POLISH_MIN_RATIO:
        reasons.append("recorta demasiado el texto")
    if pol_words > orig_words * _POLISH_MAX_RATIO:
        reasons.append("alarga demasiado el texto")

    if _FIRST_PERSON_START.search(original) and not _FIRST_PERSON_START.search(polished):
        reasons.append("deja de estar en primera persona")
    if any(phrase in polished.casefold() for phrase in _POLISH_META_PHRASES):
        reasons.append("contiene frases meta o de tercera persona")

    new_numbers = set(re.findall(r"\d+", polished)) - set(re.findall(r"\d+", original))
    if new_numbers:
        reasons.append("incluye cifras nuevas: " + ", ".join(sorted(new_numbers)))

    if offer_text:
        source = {"texto": original, "perfil": profile or {}}
        invented = _unevidenced_offer_terms(polished, offer_text, source)
        if invented:
            reasons.append("términos de la oferta sin respaldo: " + ", ".join(sorted(invented)))

    if len(_get_frequent_words(polished)) > len(frequent_before):
        reasons.append("introduce más repeticiones que el original")

    return reasons


# ===========================================================================
# 2. FUNCIÓN PRINCIPAL DE PULIDO
# ===========================================================================

def polish_text_with_ollama(text, model_name="qwen2.5:7b", profile=None, offer_text=""):
    """Reescribe un texto con Ollama y SOLO acepta el resultado si pasa los controles.

    Ollama se llama con format="json", así que el prompt pide explícitamente un JSON
    {"texto": "..."} y de ahí se extrae únicamente la cadena. Si ninguno de los dos
    intentos pasa los controles, se devuelve el texto original (con puntuación limpia).
    """
    global _LAST_POLISH_REPORT

    if not text or len(text.strip()) < 10:
        return text

    cleaned_original = _fix_grammar_and_punctuation(text)
    frequent_words = _get_frequent_words(text)

    if frequent_words:
        words_str = ", ".join(f'"{w}"' for w in frequent_words)
        avoid_instruction = (
            f"Estas palabras se repiten demasiado: [{words_str}]. Usa sinónimos o "
            "reestructura las frases para no usar cada una más de una vez."
        )
    else:
        avoid_instruction = "Elimina la repetición excesiva de conceptos y de palabras."

    main_prompt = f"""
Eres un experto en redacción de currículos en español. Reescribe el texto para que suene natural, fluido y profesional.

REGLAS:
1. {avoid_instruction}
2. Conserva TODOS los hechos: herramientas, tecnologías, cifras, empresas y logros. No agregues nada nuevo y no cambies ningún número.
3. Mantén la primera persona ("Soy", "Tengo", "He trabajado").
4. Si hay listas largas de conceptos, agrúpalos en ideas y no enumeres más de cuatro elementos seguidos. Evita empezar dos oraciones con la misma palabra.
5. Respeta las mayúsculas de nombres propios y tecnologías (Python, Power BI, Machine Learning).
6. FORMATO: responde SOLO con un JSON de esta forma: {{"texto": "<texto reescrito en una sola cadena>"}}. Sin explicaciones.

TEXTO A REESCRIBIR:
{text}
"""

    retry_prompt = f"""
Reescribe este texto en español en un solo párrafo fluido, sin repetir palabras ni enumerar más de cuatro elementos seguidos. Conserva todos los datos, cifras y nombres de tecnologías, y mantén la primera persona.
Responde SOLO con un JSON de esta forma: {{"texto": "<texto reescrito en una sola cadena>"}}

{text}
"""

    prefix_pattern = r"^(Aquí está|Texto pulido|Resultado|Resumen|Reescritura|Versión pulida):?\s*"
    attempts = []

    for label, prompt in (("ollama", main_prompt), ("ollama_reintento", retry_prompt)):
        try:
            result = _text_response(prompt, model_name)
        except Exception as exc:
            attempts.append({"intento": label, "motivos": [f"error: {exc}"]})
            continue

        polished = _extract_text_from_llm(result)
        polished = re.sub(prefix_pattern, "", polished, flags=re.IGNORECASE)
        polished = _fix_grammar_and_punctuation(polished.strip().strip('"').strip("'"))

        reasons = _polish_rejection_reasons(
            text, polished, frequent_words, profile=profile, offer_text=offer_text
        )
        attempts.append({"intento": label, "motivos": reasons})
        if not reasons:
            _LAST_POLISH_REPORT = {"origen": label, "intentos": attempts}
            return polished

    _LAST_POLISH_REPORT = {"origen": "texto_original", "intentos": attempts}
    return cleaned_original










def _text_response(prompt, model_name):
    response = _call_ollama(prompt, model_name=model_name)
    return response if isinstance(response, dict) else {}


def _local_reorder_experience(experience, offer_text):
    """Devuelve la descripción fuente en su orden original como fallback factual."""
    return str(experience.get("descripcion", "")).strip()


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


def _uses_present_tense_for_completed_role(description, experience):
    dates = str(experience.get("fechas", "")).casefold()
    if not dates or any(marker in dates for marker in ("actualidad", "presente", "current", "present")):
        return False
    present_forms = {
        "planifico", "diseño", "ejecuto", "lidero", "dirijo", "desarrollo", "implemento",
        "construyo", "utilizo", "realizo", "participo", "integro", "analizo", "gestiono",
        "coordino", "construye", "desarrolla", "implementa", "utiliza", "realiza",
        "participa", "integra", "lidera", "dirige", "planifica", "ejecuta",
    }
    words = {word.casefold() for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", description)}
    return bool(words & present_forms)


def adapt_experience_to_offer(
    experience, offer_text, model_name="qwen2.5:7b", forbidden_companies=None, diagnostics=None
):
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
    métricas del texto fuente. No inventes ningún dato. Mantén el orden lógico de las
    ideas de la experiencia fuente: alcance y liderazgo, proyectos y resultados, luego
    herramientas y responsabilidades complementarias. No pongas la conclusión al inicio
    ni dejes una oración o idea inconclusa al final. Puedes mejorar la redacción y destacar
    lo más pertinente, pero no reordenes las ideas ni cambies su sentido.
    TIEMPO VERBAL: la experiencia está fechada {experience.get('fechas', '')}. Si ya terminó,
    redacta funciones y logros en pasado ("planifiqué", "dirigí", "desarrollé",
    "implementé", "participé"). No uses presente ("planifico", "dirijo", "desarrollo",
    "implemento") ni mezcles tiempos verbales. Usa presente solo si el empleo sigue vigente.
    Mi único sector real es el que aparece en el texto fuente (ver "sectores"). Sin importar
    el sector, industria o cargo que mencione la oferta, jamás afirmes que tengo experiencia
    en ese sector si no coincide con el mío real. En vez de eso, asocia mis herramientas,
    metodologías y logros reales con lo que pide la oferta, sin nombrar el sector de la oferta
    como si fuera propio.
    Cuida la redacción: evita usar la conjunción "y" más de una vez dentro de la misma oración;
    reestructura con comas o divide en varias oraciones si es necesario.

    REGLA ABSOLUTA DE TRAZABILIDAD: la EXPERIENCIA FUENTE de abajo es la ÚNICA fuente
    autorizada de hechos (sectores, herramientas, metodologías, resultados). La oferta
    solo sirve para decidir qué parte de esa experiencia destacar primero; NUNCA es una
    fuente de hechos. Si una tecnología, sector, metodología o certificación aparece
    únicamente en la oferta y no en la EXPERIENCIA FUENTE, no la menciones bajo ninguna
    circunstancia, aunque suene relacionada.

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
           "para el puesto de", "ajustado al perfil", "alinea con los requisitos",
           "como se solicita", "mi perfil se adapta",
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
    unevidenced_offer_terms = _unevidenced_offer_terms(description, offer_text, experience)
    issues = []
    if len(description.split()) < 25:
        issues.append("respuesta vacía o menor de 25 palabras")
    if any(phrase in description.casefold() for phrase in evaluator_phrases):
        issues.append("contiene frases evaluativas o tareas futuras")
    if any(company.casefold() in description.casefold() for company in forbidden_companies):
        issues.append("menciona una organización objetivo prohibida")
    if source_overlap < 3:
        issues.append("coincidencia insuficiente con la descripción fuente")
    if unevidenced_offer_terms:
        issues.append("términos no respaldados: " + ", ".join(sorted(unevidenced_offer_terms)))
    if _uses_present_tense_for_completed_role(description, experience):
        issues.append("usa presente para una experiencia finalizada")
    accepted = not issues
    if diagnostics is not None:
        diagnostics.update({
            "ollama_consultado": True,
            "ollama_respondio": bool(result),
            "origen": "ollama" if accepted else "fallback_local",
            "motivo_fallback": issues,
        })
    if not accepted:
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


def adapt_skills_to_offer(profile, offer_text, model_name="qwen2.5:7b", diagnostics=None):
    """Prioriza habilidades y logros reales en una sola llamada local."""
    source = json.dumps({
        "aptitudes": profile.get("aptitudes", []),
        "software": profile.get("software", []),
        "nuevas_tecnologias": profile.get("nuevas_tecnologias", []),
        "competencias": profile.get("competencias", []),
        "habilidades_legacy": profile.get("habilidades", []),
        "certificaciones": profile.get("certificaciones", []),
        "logros": profile.get("logros", []),
    }, ensure_ascii=False)
    prompt = f"""
    Selecciona habilidades para un CV adaptado a una oferta laboral.
    Devuelve solo JSON con cinco listas: aptitudes_clave, herramientas, nuevas_tecnologias, competencias y logros.
    Usa exclusivamente elementos existentes en la categoría correspondiente de la fuente.
    No inventes ni reformules nombres. Elimina duplicados y ordena por relevancia para la oferta.
    aptitudes_clave debe contener máximo 7 elementos y herramientas máximo 12.
    competencias debe contener máximo 12 elementos.
    nuevas_tecnologias debe contener máximo 8 elementos y solo puede usar la categoría homónima.
    logros debe contener máximo 5 elementos copiados literalmente de la fuente.

    OFERTA:
    {offer_text[:4000]}

    FUENTE REAL:
    {source}
    """
    result = _text_response(prompt, model_name)
    selections = {
        "aptitudes_clave": result.get("aptitudes_clave", []),
        "herramientas": result.get("herramientas", []),
        "nuevas_tecnologias": result.get("nuevas_tecnologias", []),
        "competencias": result.get("competencias", []),
        "logros": result.get("logros", []),
    }
    if diagnostics is not None:
        diagnostics.update({
            "ollama_consultado": True,
            "ollama_respondio": bool(result),
            "elementos_habilidad_propuestos": sum(
                len(selections[key])
                for key in ("aptitudes_clave", "herramientas", "nuevas_tecnologias", "competencias")
                if isinstance(selections[key], list)
            ),
            "logros_propuestos": len(selections["logros"]) if isinstance(selections["logros"], list) else 0,
        })
    return selections

def _compact_profile_for_summary(profile):
    """Versión reducida del perfil para el prompt del resumen (~70% más corta)."""
    dp = profile.get("datos_personales", {})
    return {
        "datos_personales": {
            "profesion": dp.get("profesion"),
            "profesiones": dp.get("profesiones"),
        },
        "perfil_profesional": profile.get("perfil_profesional", {}),
        "formacion": profile.get("formacion", []),
        "experiencia": [
            {k: exp.get(k) for k in ("empresa", "cargo", "fechas", "sectores", "herramientas", "proyectos", "logros") if exp.get(k)}
            for exp in profile.get("experiencia", [])
        ],
        "competencias": profile.get("competencias", []),
        "certificaciones": profile.get("certificaciones", []),
        "idiomas": profile.get("idiomas", []),
    }


def analyze_offer_and_profile(offer_text, profile, model_name="qwen2.5:7b"):
    """Analiza la oferta en bloques pequeños y combina resultados validados."""
    if not offer_text or not isinstance(profile, dict):
        return _fallback_analysis(profile or {})

    offer_sample = offer_text[:5000]
    #profile_summary = json.dumps(profile, ensure_ascii=False)
    profile_summary = json.dumps(_compact_profile_for_summary(profile), ensure_ascii=False)
    overview_prompt = f"""
    Analiza únicamente esta oferta laboral. Devuelve SOLO JSON con:
    cargo_detectado, nivel_rol (junior, intermedio, avanzado o no determinado),
    prioridades, requisitos_no_evidenciados.
    No describas experiencia del candidato y no inventes datos.

    OFERTA:
    {offer_sample}
    """
    overview = _text_response(overview_prompt, model_name)
    overview_responded = bool(overview)
    overview_model_fields = [
        key for key, value in overview.items()
        if value not in (None, "", [], {})
    ]
    local_overview = _local_offer_overview(offer_text, profile)
    if not overview.get("cargo_detectado") or overview.get("cargo_detectado") == "NO_EVIDENCIADO":
        overview["cargo_detectado"] = local_overview["cargo_detectado"]
    if not overview.get("nivel_rol") or overview.get("nivel_rol") == "no determinado":
        overview["nivel_rol"] = local_overview["nivel_rol"]
    if not overview.get("prioridades"):
        overview["prioridades"] = local_overview["prioridades"]
    summary_prompt = f"""
    Redacta el perfil profesional de un CV para esta oferta.
    Devuelve SOLO JSON con resumen_profesional de 90 a 125 palabras.
    El texto DEBE comenzar con "Soy" o "Tengo" y mantenerse en primera persona durante
    todo el resumen. Usa formas como "He desarrollado", "He trabajado", "Mi experiencia"
    y "Puedo aportar". No escribas "Su trayectoria", "su experiencia", "el candidato",
    "el profesional" ni describas a Anderson desde fuera.
    No uses frases como "perfil maestro", "responsabilidades registradas", "según la
    oferta", "objetivos de la oferta" o "alineado con la oferta". Usa exclusivamente
    hechos del perfil maestro.
    No conviertas el sector o problema de la oferta en experiencia previa. Adapta el foco
    al nivel y prioridades entregados, pero no inventes empresas, cargos, sectores ni métricas.
    Integra entre dos y cuatro prioridades de la oferta en frases naturales, relacionadas
    con evidencias reales. No copies listas de responsabilidades ni verbos en infinitivo.
    No uses una plantilla genérica de "Ingeniero con experiencia en..."; redacta una síntesis
    personal y concreta que conecte mi experiencia real con esta vacante.
    Mis sectores reales son únicamente los que aparecen en las experiencias del perfil
    maestro (campo "sectores"). Sin importar qué sector, industria o rubro mencione la
    oferta (crédito, salud, retail, banca, logística, etc.), NUNCA afirmes tener experiencia
    en un sector distinto al mío real. En su lugar, conecta la oferta con mis técnicas,
    herramientas y logros reales, sin nombrar el sector de la oferta como propio.
    Evita repetir la conjunción "y" dentro de una misma oración; varía la redacción.

    REGLA ABSOLUTA DE TRAZABILIDAD: el perfil maestro es la ÚNICA fuente autorizada para
    afirmar experiencia, conocimientos, sectores, herramientas o resultados del candidato.
    La oferta NO es una fuente de experiencia, solo sirve para priorizar qué contar primero.
    Distingue siempre entre "requisito de la oferta" y "evidencia del candidato": solo puedes
    afirmar algo si existe evidencia literal en el perfil maestro. Si una tecnología, sector,
    metodología o certificación aparece solo en la oferta, NO la incorpores como experiencia
    propia, aunque el tema parezca similar (por ejemplo, "mercados financieros" no equivale a
    "crédito" ni a "riesgo financiero" "Azure" "Databricks" "Data Lake" "Lakehouse"; no hagas inferencias por semejanza semántica).

    NIVEL Y PRIORIDADES:
    {json.dumps(overview, ensure_ascii=False)}

    PERFIL MAESTRO:
    {profile_summary}
    """
    summary_result = _text_response(summary_prompt, model_name)
    generated_summary = str(summary_result.get("resumen_profesional", "")).strip()
    summary_attempts = [{
        "ollama_respondio": bool(summary_result),
        "valido": summary_is_factual(generated_summary, profile, offer_text),
        "motivos_rechazo": (
            _summary_validation_issues(generated_summary, profile, offer_text)
            if summary_result else [_LAST_OLLAMA_ERROR or "Ollama no devolvió respuesta"]
        ),
    }]
    summary_source = "ollama" if summary_attempts[0]["valido"] else ""
    if not summary_source:
        retry_prompt = summary_prompt + """

    IMPORTANTE: el intento anterior pudo haber incluido información no respaldada por
    el perfil maestro. Esta vez sé aún más estricto: usa ÚNICAMENTE lo que está escrito
    literalmente en el PERFIL MAESTRO. Si la oferta pide algo que no tengo documentado,
    simplemente no lo menciones.
    """
        summary_result = _text_response(retry_prompt, model_name)
        generated_summary = str(summary_result.get("resumen_profesional", "")).strip()
        retry_valid = summary_is_factual(generated_summary, profile, offer_text)
        summary_attempts.append({
            "ollama_respondio": bool(summary_result),
            "valido": retry_valid,
            "motivos_rechazo": (
                _summary_validation_issues(generated_summary, profile, offer_text)
                if summary_result else [_LAST_OLLAMA_ERROR or "Ollama no devolvió respuesta"]
            ),
        })
        if retry_valid:
            summary_source = "ollama_reintento"
        else:
            generated_summary = ""
            summary_source = "fallback_local"

    active_model = os.getenv("OLLAMA_MODEL", model_name)
    detected_role = overview.get("cargo_detectado", "NO_EVIDENCIADO")
    if not detected_role or detected_role == "NO_EVIDENCIADO":
        detected_role = _extract_role_from_offer(offer_text)
    summary_accepted = summary_source.startswith("ollama")
    return {
        "cargo_detectado": detected_role,
        "modelo": f"ollama-{active_model}",
        "analisis_oferta_ollama_consultado": True,
        "analisis_oferta_origen": "ollama_con_apoyo_local" if overview_responded else "fallback_local",
        "analisis_oferta_ollama_respondio": overview_responded,
        "analisis_oferta_campos_ollama": overview_model_fields,
        "resumen_origen": summary_source or "fallback_local",
        "resumen_intentos": summary_attempts,
        "motivo": (
            "Resumen generado y validado por Ollama"
            if summary_accepted
            else "Los resúmenes de Ollama no superaron la validación; se usará el fallback local"
        ),
        "palabras_clave": overview.get("prioridades", [])[:30],
        "resumen_profesional": generated_summary,
        "experiencia_priorizada": [],
        "logros_priorizados": [],
        "responsabilidades_priorizadas": [],
        "requisitos_no_evidenciados": overview.get("requisitos_no_evidenciados", [])[:15],
        "nivel_ajuste": overview.get("nivel_rol", "No determinado"),
        "estado": "resumen generado con Ollama" if summary_accepted else "resumen local de fallback",
    }