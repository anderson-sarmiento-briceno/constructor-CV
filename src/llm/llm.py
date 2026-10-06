import json
import re
import unicodedata

from src.llm.client import LLMError, chat, model_name

_LAST_LLM_ERROR = ""

# La oferta se envía una sola vez por llamada; 5000 caracteres cubren el texto útil
# sin agotar el límite gratuito de Groq (8K tokens por minuto).
_OFFER_CHARS = 5000

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

# Reglas de veracidad compartidas por todas las llamadas (se envían como mensaje system).
_SYSTEM_RULES = """Eres un redactor experto de hojas de vida en español. Adaptas mi CV a una oferta laboral con redacción natural, fluida, concreta y profesional, sin inventar nada.

REGLAS DE VERACIDAD (obligatorias):
1. Mi PERFIL o mis EXPERIENCIAS FUENTE son la única fuente de hechos: cargos, empresas, fechas, sectores, herramientas, metodologías, proyectos, métricas y certificaciones.
2. La OFERTA solo sirve para decidir qué hechos reales destacar y en qué orden. Nunca es fuente de experiencia. Si una tecnología, sector, metodología o certificación aparece solo en la oferta, no la menciones, aunque parezca relacionada: no hagas inferencias por semejanza (por ejemplo, "mercados financieros" no equivale a "riesgo de crédito").
3. Mis sectores son únicamente los del campo "sectores". No afirmes experiencia en el sector de la oferta; conecta la oferta con mis herramientas, métodos y logros reales.
4. Menciona años de experiencia o cantidad de proyectos solo si están escritos en mi perfil.
5. El trabajo independiente no es una empresa: escribe "Como consultor freelance", nunca "En Consultor Freelance".
6. Escribe en primera persona, como texto propio del CV. Nada de tercera persona ni frases meta ("el candidato", "el profesional", "según la oferta", "perfil maestro", "mi perfil se adapta", "para el puesto de", "como se solicita").
7. No nombres la empresa de la oferta, no la menciones ni describas tareas futuras.
8. Cada cifra debe quedar unida al mismo resultado y a la misma acción que en la fuente; nunca la traslades a otro logro ni la cambies. Puedes reordenar las ideas, pero si la fuente dice "Construí informes… mejorando un X%", no escribas "Implementé tableros… mejorando un X%".
9. No exageres el alcance: si la fuente dice "insumo técnico para la certificación", no escribas que lograste o permitiste la certificación; no cambies "construí" o "desarrollé" por "lideré" si la fuente no dice que lideraste.
10. Respeta las mayúsculas de nombres propios y tecnologías.
11. Responde solo con el JSON pedido."""

# Caracteres que el modelo usa a veces y que la fuente del PDF no tiene
# (por ejemplo, el guion U+2011 de "Scikit‑learn" se imprimía como "Scikitnlearn").
_UNICODE_FIXES = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
})


def _significant_terms(text):
    """Palabras/siglas de 3+ letras relevantes, ignorando conectores comunes."""
    words = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", text or "")
    return {word.casefold() for word in words if word.casefold() not in _STOPWORDS_ES}


def _stem(word, size=6):
    """Raíz simple: sin acentos, minúsculas y primeras letras (analítica ~ analíticos)."""
    flat = "".join(
        ch for ch in unicodedata.normalize("NFKD", word.casefold())
        if not unicodedata.combining(ch)
    )
    return flat[:size]


def _stems_of(text):
    return {_stem(word) for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", text or "")}


def _unevidenced_offer_terms(generated_text, offer_text, source_fact):
    """Términos que están en la oferta y en el texto generado, pero sin raíz en la fuente real."""
    source_stems = _stems_of(json.dumps(source_fact, ensure_ascii=False))
    candidate_terms = _significant_terms(offer_text) & _significant_terms(generated_text)
    return {term for term in candidate_terms if _stem(term) not in source_stems}


_SUMMARY_CLICHES = (
    "puedo aportar", "mi capacidad para", "me desempeño en", "decisiones estratégicas",
    "conocimiento profundo", "soluciones escalables", "insights accionables",
)


# Exageraciones que el modelo repitió aunque el prompt las prohíbe: solo se aceptan
# si la fuente dice lo mismo (patrón buscado en el texto, motivo del rechazo).
_OVERCLAIMS = (
    (r"\blider\w*", "afirma liderazgo que la fuente no menciona"),
    (r"\b(?:permiti\w*|logr\w*|obtuv\w*|consegu\w*|alcanz\w*)\b[^.]{0,40}\bcertificaci",
     "afirma haber logrado una certificación; la fuente solo dice que aportó a ella"),
)


def _misplaced_metric_issues(description, experience):
    """Porcentajes unidos a una acción distinta de la fuente.

    Para cada porcentaje se toma la frase (entre comas) que lo contiene y se cuentan las
    palabras que están en ESTA experiencia, pero solo en oraciones que no tienen ese
    porcentaje: si son 3 o más, la cifra se trasladó a otra acción (p. ej., una mejora
    que en la fuente es de unos informes aparece atribuida a unos tableros).
    """
    source_sentences = [
        re.sub(r"(\d)\s+%", r"\1%", sentence)
        for value in re.findall(r'"((?:[^"\\]|\\.)*)"', json.dumps(experience, ensure_ascii=False))
        for sentence in re.split(r"(?<=[.!?])\s+", value)
    ]
    experience_terms = {_stem(term) for sentence in source_sentences for term in _significant_terms(sentence)}
    issues = []
    for clause in re.split(r"[,;:]|(?<=[.!?])\s+", re.sub(r"(\d)\s+%", r"\1%", description or "")):
        for metric in re.findall(r"\d+(?:[.,]\d+)?%", clause):
            metric_terms = {
                _stem(term)
                for sentence in source_sentences if re.search(rf"(?<![\d.,]){re.escape(metric)}", sentence)
                for term in _significant_terms(sentence)
            }
            if not metric_terms:
                continue  # la cifra no está en la experiencia: lo reporta el control de cifras
            clause_terms = {_stem(term) for term in _significant_terms(clause)}
            borrowed = (clause_terms & experience_terms) - metric_terms
            if len(borrowed) >= 3:
                issues.append(f"la cifra {metric} aparece unida a una acción distinta de la fuente: «{clause.strip()}»")
    return issues


def _overclaim_issues(text, source):
    source_text = json.dumps(source, ensure_ascii=False) if not isinstance(source, str) else source
    return [
        reason for pattern, reason in _OVERCLAIMS
        if re.search(pattern, text or "", re.IGNORECASE) and not re.search(pattern, source_text, re.IGNORECASE)
    ]


def _summary_validation_issues(summary, profile, offer_text, include_style=True, requirements=None):
    """Motivos de rechazo del resumen. include_style=False deja solo los de veracidad y
    formato obligatorio (sin la regla de la "y" ni las muletillas).

    requirements: requisitos de la oferta detectados en el análisis. Un término de la
    oferta sin respaldo en el perfil es de veracidad si forma parte de esos requisitos
    (se atribuiría algo que no se tiene); si es solo vocabulario, es de estilo. Sin lista
    de requisitos, todos cuentan como veracidad.
    """
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
    if "%" in summary_text or "por ciento" in summary_lower:
        issues.append("incluye porcentajes (van en la sección de experiencia)")
    issues.extend(_overclaim_issues(summary_text, profile))
    if include_style:
        cliches = [phrase for phrase in _SUMMARY_CLICHES if phrase in summary_lower]
        if cliches:
            issues.append("usa muletillas: " + ", ".join(cliches))
        # Dos "y" en una oración es español normal ("Diseño y entreno modelos con Python y
        # Spark"); tres o más ya es una oración encadenada que conviene dividir.
        for sentence in re.split(r"(?<=[.!?])\s+", summary_text):
            if len(re.findall(r"\b[ye]\b", sentence.casefold())) > 2:
                issues.append(f'oración con tres o más "y" (divídela en dos oraciones): «{sentence.strip()}»')

    offer_terms = {term for term in _significant_terms(offer_text) if len(term) >= 4}
    summary_terms = _significant_terms(summary)
    profile_stems = _stems_of(profile_text)
    invented = [
        term for term in (offer_terms & summary_terms)
        if _stem(term) not in profile_stems
    ]
    if requirements:
        requirement_stems = _stems_of(" ".join(str(item) for item in requirements))
        claimed = sorted(term for term in invented if _stem(term) in requirement_stems)
        wording = sorted(term for term in invented if _stem(term) not in requirement_stems)
    else:
        claimed, wording = sorted(invented), []
    if claimed:
        issues.append("incluye términos de oferta sin evidencia: " + ", ".join(claimed))
    if wording and include_style:
        issues.append("usa vocabulario de la oferta que no está en el perfil: " + ", ".join(wording))
    return issues


def summary_is_factual(summary, profile, offer_text, requirements=None):
    """Valida veracidad y formato obligatorio (los detalles de estilo no cuentan)."""
    return not _summary_validation_issues(
        summary, profile, offer_text, include_style=False, requirements=requirements
    )


def _compact(data):
    """JSON compacto y sin campos vacíos, para gastar menos tokens."""
    def prune(value):
        if isinstance(value, dict):
            pruned = {key: prune(item) for key, item in value.items()}
            return {key: item for key, item in pruned.items() if item not in (None, "", [], {})}
        if isinstance(value, list):
            return [prune(item) for item in value if item not in (None, "", [], {})]
        return value
    return json.dumps(prune(data), ensure_ascii=False, separators=(",", ":"))


def _normalize(value):
    """Limpia los textos de la respuesta: caracteres que el PDF no puede mostrar y
    porcentajes con espacio ("35 %" -> "35%") para que todo el CV use el mismo formato."""
    if isinstance(value, str):
        return re.sub(r"(\d)\s+%", r"\1%", value.translate(_UNICODE_FIXES))
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _ask(user_prompt):
    """Consulta al modelo con las reglas de veracidad; devuelve {} si falla."""
    global _LAST_LLM_ERROR
    try:
        result = chat(_SYSTEM_RULES, user_prompt)
    except LLMError as exc:
        _LAST_LLM_ERROR = str(exc)
        return {}
    _LAST_LLM_ERROR = ""
    return _normalize(result) if isinstance(result, dict) else {}


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
    # Solo las palabras guía ignoran mayúsculas; el cargo debe empezar con mayúscula.
    # (Antes "como" + IGNORECASE tomaba frases como "como habilitadores de la estrategia".)
    patterns = (
        r"(?i:buscamos|vacante para)\s+(?i:un\(?a\)?\s+)?([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ& ]{3,60})",
        r"(?i:rol|cargo)\s+(?i:de|para)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ& ]{3,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, offer_text or "")
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
        "motivo": _LAST_LLM_ERROR or "El modelo no respondió",
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


def _uses_present_tense_for_completed_role(description, experience):
    dates = str(experience.get("fechas", "")).casefold()
    if not dates or any(marker in dates for marker in ("actualidad", "presente", "current", "present")):
        return False
    # Sin "diseño" ni "desarrollo": también son sustantivos ("el diseño de redes")
    # y provocaban rechazos falsos.
    present_forms = {
        "planifico", "ejecuto", "lidero", "dirijo", "implemento",
        "construyo", "utilizo", "realizo", "participo", "integro", "analizo", "gestiono",
        "coordino", "construye", "desarrolla", "implementa", "utiliza", "realiza",
        "participa", "integra", "lidera", "dirige", "planifica", "ejecuta",
    }
    words = {word.casefold() for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", description)}
    return bool(words & present_forms)


_EVALUATOR_PHRASES = (
    "el candidato", "el perfil", "nivel de ajuste", "se ajusta a la oferta",
    "en esta empresa", "apoyaré", "implementaré", "contribuiré",
    "pasantía", "pasantia", "pasante", "internship", "práctica profesional", "practica profesional",
    "para el puesto de", "ajustado al perfil", "alinea con los requisitos",
    "como se solicita", "mi perfil se adapta",
)


def _experience_issues(description, experience, offer_text, forbidden_companies, profile=None):
    """Motivos para rechazar una experiencia reescrita (lista vacía = aceptada).

    Un término de la oferta se permite si aparece en algún lugar del perfil (no solo en
    esta experiencia): así las palabras de uso general que la persona sí usa no provocan
    rechazos, y lo que solo trae la oferta se sigue bloqueando. Las cifras y las
    exageraciones se validan contra esta experiencia en particular.
    """
    source_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{5,}", experience.get("descripcion", ""))
    }
    description_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{5,}", description)
    }
    unevidenced = _unevidenced_offer_terms(description, offer_text, profile or experience)
    number_pattern = r"\d+(?:[.,]\d+)?"
    new_numbers = (
        set(re.findall(number_pattern, description))
        - set(re.findall(number_pattern, json.dumps(experience, ensure_ascii=False)))
    )
    issues = []
    if len(description.split()) < 25:
        issues.append("respuesta vacía o menor de 25 palabras")
    if any(phrase in description.casefold() for phrase in _EVALUATOR_PHRASES):
        issues.append("contiene frases evaluativas o tareas futuras")
    if any(company.casefold() in description.casefold() for company in forbidden_companies):
        issues.append("menciona una organización objetivo prohibida")
    if len(source_words & description_words) < 3:
        issues.append("coincidencia insuficiente con la descripción fuente")
    if unevidenced:
        issues.append("términos no respaldados: " + ", ".join(sorted(unevidenced)))
    if new_numbers:
        issues.append("cifras que no están en esta experiencia: " + ", ".join(sorted(new_numbers)))
    issues.extend(_overclaim_issues(description, experience))
    issues.extend(_misplaced_metric_issues(description, experience))
    if _uses_present_tense_for_completed_role(description, experience):
        issues.append("usa presente para una experiencia finalizada")
    return issues


def _experience_proposals(result):
    """{indice: descripcion_adaptada} a partir de la respuesta del modelo."""
    items = result.get("experiencias") if isinstance(result.get("experiencias"), list) else []
    return {
        item["indice"]: str(item.get("descripcion_adaptada", "")).strip()
        for item in items
        if isinstance(item, dict) and isinstance(item.get("indice"), int)
    }


def adapt_experiences_and_skills(profile, experiences, offer_text, forbidden_companies=None):
    """Una sola llamada: reescribe cada experiencia real y selecciona habilidades.

    Cada experiencia se valida por separado; si se rechaza, vuelve a su texto original.
    """
    forbidden_companies = forbidden_companies or []
    skills_source = {
        "aptitudes": profile.get("aptitudes", []),
        "software": profile.get("software", []),
        "nuevas_tecnologias": profile.get("nuevas_tecnologias", []),
        "competencias": profile.get("competencias", []),
    }
    source_experiences = [{"indice": index, **experience} for index, experience in enumerate(experiences)]
    prompt = f"""TAREA: adapta cada una de mis experiencias a la oferta y selecciona mis habilidades más relevantes para ella.

Devuelve JSON con esta forma:
{{"experiencias":[{{"indice":0,"descripcion_adaptada":"..."}}],"aptitudes_clave":[],"herramientas":[],"nuevas_tecnologias":[],"competencias":[]}}

EXPERIENCIAS: una entrada por cada experiencia fuente, con el mismo "indice".
- Entre 80 y 130 palabras, como descripción propia y directa de lo que hice.
- Usa solo los hechos de ESA experiencia (no mezcles datos entre experiencias). Conserva literalmente empresa, herramientas, proyectos y métricas.
- Usa el vocabulario de la experiencia fuente: no añadas técnicas ni palabras de la oferta que no estén escritas en ella (por ejemplo, no escribas "feature engineering", "insights" o "clientes" si la fuente no los menciona).
- Destaca primero lo más pertinente para la oferta, con un hilo lógico, y cierra con una idea completa.
- Tiempo verbal: pasado si la experiencia terminó ("dirigí", "desarrollé", "implementé"); presente solo si sus fechas dicen que sigue vigente. No mezcles tiempos.

HABILIDADES: copia nombres exactos de la categoría correspondiente, sin reformularlos, sin duplicados y ordenados por relevancia para la oferta.
- aptitudes_clave: máximo 7, de "aptitudes".
- herramientas: máximo 12, de "software".
- nuevas_tecnologias: máximo 8, de "nuevas_tecnologias".
- competencias: máximo 12, de "competencias".

ORGANIZACIONES DE LA OFERTA (prohibido escribirlas): {", ".join(forbidden_companies) or "ninguna detectada"}

OFERTA:
{(offer_text or "")[:_OFFER_CHARS]}

EXPERIENCIAS FUENTE:
{_compact(source_experiences)}

HABILIDADES:
{_compact(skills_source)}"""
    result = _ask(prompt)
    proposals = _experience_proposals(result)
    def issues_of(text, experience):
        return _experience_issues(text, experience, offer_text, forbidden_companies, profile)

    reviews = {
        index: issues_of(proposals.get(index, ""), experience)
        for index, experience in enumerate(experiences)
    }

    # Reintento de cada experiencia rechazada en su propia llamada (juntas, el modelo
    # mezclaba cifras entre experiencias): texto rechazado, motivos y palabras prohibidas,
    # sin reenviar la oferta ni las habilidades.
    rejected = [index for index, issues in reviews.items() if issues] if result else []
    retry_proposals = {}
    for index in rejected:
        forbidden_terms = sorted({
            term.strip()
            for issue in reviews[index] if issue.startswith("términos no respaldados")
            for term in issue.split(":", 1)[1].split(",") if term.strip()
        })
        forbidden_line = (
            "PALABRAS PROHIBIDAS (no están en mi perfil; no las uses ni sus variantes): "
            + ", ".join(forbidden_terms) + "\n"
        ) if forbidden_terms else ""
        retry_prompt = f"""TAREA: corrige esta descripción de experiencia, que fue rechazada.

Devuelve JSON con esta forma:
{{"descripcion_adaptada":"..."}}

- Parte del TEXTO RECHAZADO y corrige solo lo que indican los MOTIVOS; conserva su enfoque.
- Entre 80 y 130 palabras, en primera persona, solo con hechos, cifras y vocabulario de esta EXPERIENCIA FUENTE.
- Pasado si la experiencia terminó; presente solo si sigue vigente.
{forbidden_line}ORGANIZACIONES DE LA OFERTA (prohibido escribirlas): {", ".join(forbidden_companies) or "ninguna detectada"}

MOTIVOS: {"; ".join(reviews[index])}

TEXTO RECHAZADO:
{proposals.get(index, "") or "(el modelo no devolvió texto para esta experiencia)"}

EXPERIENCIA FUENTE:
{_compact(experiences[index])}"""
        retry_proposals[index] = str(_ask(retry_prompt).get("descripcion_adaptada", "")).strip()

    descriptions = []
    diagnostics = []
    for index, experience in enumerate(experiences):
        proposed = proposals.get(index, "")
        issues = reviews[index]
        origin = "llm" if not issues else "fallback_local"
        attempts = 1
        if index in rejected:
            attempts = 2
            retry_text = retry_proposals.get(index, "")
            retry_issues = issues_of(retry_text, experience)
            if not retry_issues:
                proposed, issues, origin = retry_text, [], "llm_reintento"
            else:
                issues = issues + [f"reintento: {reason}" for reason in retry_issues]
        descriptions.append(proposed if origin != "fallback_local" else str(experience.get("descripcion", "")).strip())
        diagnostics.append({
            "llm_consultado": True,
            "llm_respondio": bool(result),
            "origen": origin,
            "intentos": attempts,
            "motivo_fallback": issues if result else [_LAST_LLM_ERROR or "el modelo no respondió"],
            "texto_propuesto": proposed,
        })

    selections = {
        key: result.get(key, []) if isinstance(result.get(key, []), list) else []
        for key in ("aptitudes_clave", "herramientas", "nuevas_tecnologias", "competencias")
    }
    skills_diagnostic = {
        "llm_consultado": True,
        "llm_respondio": bool(result),
        "elementos_habilidad_propuestos": sum(len(items) for items in selections.values()),
    }
    return {
        "descripciones": descriptions,
        "diagnosticos": diagnostics,
        "habilidades": selections,
        "diagnostico_habilidades": skills_diagnostic,
    }


def _compact_profile_for_summary(profile):
    """Perfil reducido para el resumen. De datos_personales solo viajan profesion y profesiones."""
    dp = profile.get("datos_personales", {})
    return {
        "datos_personales": {
            "profesion": dp.get("profesion"),
            "profesiones": dp.get("profesiones"),
        },
        "perfil_profesional": profile.get("perfil_profesional", {}),
        "formacion": profile.get("formacion", []),
        # Sin las herramientas de cada experiencia (traen clases como GradientBoostingRegressor
        # y llevaban al modelo a enumerarlas); la lista general "software" basta para el resumen.
        "experiencia": [
            {k: exp.get(k) for k in ("empresa", "cargo", "fechas", "sectores", "proyectos") if exp.get(k)}
            for exp in profile.get("experiencia", [])
        ],
        "software": profile.get("software", []),
        "competencias": profile.get("competencias", []),
        "certificaciones": profile.get("certificaciones", []),
        "idiomas": profile.get("idiomas", []),
    }


_SUMMARY_INSTRUCTIONS = """resumen_profesional: entre 90 y 120 palabras, en 4 o 5 oraciones. Es una síntesis de quién soy como profesional para esta oferta, NO un resumen de mis experiencias (esas ya aparecen en su propia sección).
- Oración 1: empieza con "Soy" y la profesión de "profesiones" que mejor corresponda a la oferta, con mi formación. Si mencionas años, son mi trayectoria total tal como la dice el perfil ("más de N años de trayectoria en..."); nunca los unas a una sola profesión ("Científico de Datos con 15 años").
- Oraciones 2 y 3: dos o tres fortalezas centrales que respondan a las prioridades de la oferta, expresadas como capacidades respaldadas por mi perfil (qué sé hacer y para qué sirve), no como una lista de proyectos.
- Menciona como máximo 5 herramientas, elegidas de "software" según lo que prioriza la oferta. Si la oferta pide una tecnología que no está en mi perfil, no la nombres: destaca mi herramienta real más cercana (por ejemplo, Spark para procesamiento de grandes volúmenes), sin presentarla como equivalente. No nombres algoritmos ni clases de librerías.
- Oración final: mi diferencial real según el perfil, sin exagerar.
- No repitas proyectos, logros ni cifras de la sección de experiencia; sin porcentajes.
- No encadenes más de dos "y" en una oración: si hacen falta más, divídela en dos oraciones. Nunca quites la "y" final de una enumeración ni dejes listas unidas solo con comas ("rigor, mejora, enfoque" está mal). Cada idea aparece una sola vez. Oraciones de menos de 25 palabras, con verbos concretos.
- Prohibido: "Puedo aportar", "Mi capacidad para", "Me desempeño en", "decisiones estratégicas", "conocimiento profundo", "soluciones escalables", "insights accionables" y plantillas genéricas.

EJEMPLO DE ESTILO (es otra persona y otra profesión: imita solo el tono y la estructura, nunca sus datos):
"Soy Arquitecta, especialista en vivienda social, con más de diez años de trayectoria en proyectos públicos. Diseño conjuntos habitacionales que equilibran costo, normativa y calidad de vida. Coordino equipos de obra y consultores para cumplir cronogramas exigentes. Trabajo con AutoCAD, Revit y Excel para presupuestar con precisión. Mi diferencial es entender a la vez el diseño, la obra y a las comunidades que la habitan.\""""


def offer_requirements(analysis):
    """Requisitos de la oferta según el análisis del modelo (prioridades + no evidenciados)."""
    items = []
    for key in ("prioridades", "palabras_clave", "requisitos_no_evidenciados"):
        value = (analysis or {}).get(key)
        if isinstance(value, list):
            items += [str(item) for item in value]
    return items


def analyze_offer_and_profile(offer_text, profile):
    """Una llamada analiza la oferta y redacta el resumen; reintenta solo el resumen si se rechaza."""
    if not offer_text or not isinstance(profile, dict):
        return _fallback_analysis(profile or {})

    profile_summary = _compact(_compact_profile_for_summary(profile))
    prompt = f"""TAREA: analiza la oferta y redacta mi perfil profesional para ella.

Devuelve JSON con:
- cargo_detectado: cargo que busca la oferta.
- nivel_rol: "junior", "intermedio", "avanzado" o "no determinado".
- prioridades: hasta 10 requisitos o temas clave de la oferta, en pocas palabras cada uno.
- requisitos_no_evidenciados: requisitos de la oferta que no aparecen en mi perfil.
- {_SUMMARY_INSTRUCTIONS}

OFERTA:
{offer_text[:_OFFER_CHARS]}

PERFIL:
{profile_summary}"""
    result = _ask(prompt)
    overview_responded = bool(result)
    overview = {
        key: result.get(key)
        for key in ("cargo_detectado", "nivel_rol", "prioridades", "requisitos_no_evidenciados")
    }
    overview_model_fields = [key for key, value in overview.items() if value not in (None, "", [], {})]
    local_overview = _local_offer_overview(offer_text, profile)
    if not overview.get("cargo_detectado") or overview.get("cargo_detectado") == "NO_EVIDENCIADO":
        overview["cargo_detectado"] = local_overview["cargo_detectado"]
    if not overview.get("nivel_rol") or overview.get("nivel_rol") == "no determinado":
        overview["nivel_rol"] = local_overview["nivel_rol"]
    if not isinstance(overview.get("prioridades"), list) or not overview["prioridades"]:
        overview["prioridades"] = local_overview["prioridades"]
    if not isinstance(overview.get("requisitos_no_evidenciados"), list):
        overview["requisitos_no_evidenciados"] = []

    requirements = offer_requirements(overview) if overview_responded else None

    def review(text, responded):
        """Problemas de veracidad (rechazan siempre) y de estilo (piden reintento)."""
        if not responded:
            return {"llm_respondio": False, "valido": False, "texto_propuesto": "",
                    "motivos_rechazo": [_LAST_LLM_ERROR or "el modelo no respondió"], "advertencias_estilo": []}
        hard = _summary_validation_issues(text, profile, offer_text, include_style=False, requirements=requirements)
        style = [
            issue for issue in _summary_validation_issues(text, profile, offer_text, requirements=requirements)
            if issue not in hard
        ]
        return {"llm_respondio": True, "valido": not hard, "texto_propuesto": text,
                "motivos_rechazo": hard, "advertencias_estilo": style}

    first = review(str(result.get("resumen_profesional", "")).strip(), overview_responded)
    summary_attempts = [first]

    # Reintento solo del resumen cuando hubo cualquier problema: se envía el texto
    # rechazado para que el modelo lo corrija, sin reenviar la oferta completa.
    retry = None
    if overview_responded and (first["motivos_rechazo"] or first["advertencias_estilo"]):
        issues = first["motivos_rechazo"] + first["advertencias_estilo"]
        rejected_terms = []
        for issue in issues:
            if "términos de oferta sin evidencia" in issue or "vocabulario de la oferta" in issue:
                rejected_terms += [t.strip() for t in issue.split(":", 1)[1].split(",") if t.strip()]
        forbidden_line = (
            "PALABRAS PROHIBIDAS (vienen de la oferta y no están en mi perfil; no las uses ni sus variantes): "
            + ", ".join(rejected_terms) + "\n"
        ) if rejected_terms else ""
        retry_prompt = f"""TAREA: corrige mi perfil profesional. Parte del TEXTO RECHAZADO y corrige solo lo que indican los motivos; conserva lo que está bien.
MOTIVOS: {"; ".join(issues)}
{forbidden_line}Usa únicamente lo que está escrito en mi PERFIL. Si la oferta pide algo que no tengo documentado, no lo menciones.

Devuelve JSON con:
- {_SUMMARY_INSTRUCTIONS}

TEXTO RECHAZADO:
{first["texto_propuesto"]}

PRIORIDADES DE LA OFERTA:
{_compact(overview["prioridades"])}

PERFIL:
{profile_summary}"""
        retry_result = _ask(retry_prompt)
        retry = review(str(retry_result.get("resumen_profesional", "")).strip(), bool(retry_result))
        summary_attempts.append(retry)

    # Se elige el primer texto sin problemas; si no lo hay, el que solo tenga detalles de
    # estilo (el reintento primero). Con problemas de veracidad nunca se usa.
    candidates = [("llm", first)] + ([("llm_reintento", retry)] if retry else [])
    clean = [(origin, item) for origin, item in candidates if item["valido"] and not item["advertencias_estilo"]]
    truthful = [(origin, item) for origin, item in reversed(candidates) if item["valido"]]
    chosen = (clean or truthful or [("fallback_local", {"texto_propuesto": ""})])[0]
    summary_source, generated_summary = chosen[0], chosen[1]["texto_propuesto"]

    detected_role = overview.get("cargo_detectado") or _extract_role_from_offer(offer_text)
    summary_accepted = summary_source.startswith("llm")
    return {
        "cargo_detectado": detected_role,
        "modelo": f"groq-{model_name()}",
        "analisis_oferta_llm_consultado": True,
        "analisis_oferta_origen": "llm_con_apoyo_local" if overview_responded else "fallback_local",
        "analisis_oferta_llm_respondio": overview_responded,
        "analisis_oferta_campos_llm": overview_model_fields,
        "resumen_origen": summary_source,
        "resumen_intentos": summary_attempts,
        "motivo": (
            "Resumen generado y validado por el modelo"
            if summary_accepted
            else "Los resúmenes del modelo no superaron la validación; se usará el fallback local"
        ),
        "palabras_clave": overview["prioridades"][:30],
        "resumen_profesional": generated_summary,
        "experiencia_priorizada": [],
        "logros_priorizados": [],
        "responsabilidades_priorizadas": [],
        "requisitos_no_evidenciados": overview["requisitos_no_evidenciados"][:15],
        "nivel_ajuste": overview.get("nivel_rol", "No determinado"),
        "estado": "resumen generado con el modelo" if summary_accepted else "resumen local de fallback",
    }
