import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction.word_reader import extract_text_from_docx
from src.llm.gemini import (
    adapt_experience_to_offer,
    adapt_skills_to_offer,
    analyze_offer_and_profile,
    summary_is_factual,
    polish_text_with_ollama,
    _significant_terms,
)
from src.matching.matcher import classify_requirements
from src.rendering.pdf_renderer import build_cv_html, render_cv_to_pdf_model
from src.validation.validation import validate_claims_against_profile


def load_profile(profile_path):
    with open(profile_path, "r", encoding="utf-8") as file:
        return json.load(file)


def extract_offer_organizations(offer_text, offer_name=""):
    """Obtiene nombres probables de organizaciones para impedir que se inventen empleos."""
    candidates = set()
    filename_stem = Path(offer_name).stem.replace("_", " ")
    filename_words = re.findall(r"[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9&.-]+", filename_stem)
    if filename_words:
        candidates.add(" ".join(filename_words))

    patterns = [
        r"(?:empresa|compañía|compania|organización|organizacion|cliente|empleador)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&.-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&.-]*){0,3})",
        r"(?:en|para)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&.-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&.-]*){0,2})",
    ]
    for pattern in patterns:
        candidates.update(re.findall(pattern, offer_text or ""))

    ignored = {"Python", "Power BI", "SQL", "Excel", "PostgreSQL", "Ollama", "WordPress"}
    return sorted({item.strip() for item in candidates if item.strip() not in ignored}, key=len, reverse=True)


# Conectores mínimos (no palabras de CV) usados solo para detectar duplicados de
# redacción. A diferencia de _significant_terms (firewall anti-invención), aquí NO
# se filtran palabras como "gestión" o "proyecto": si se repiten, también cuentan.
_DEDUPE_CONNECTORS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "en", "con", "para", "por", "y", "o", "a", "que", "su", "sus", "mi",
}


def _dedupe_words(text):
    words = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", text or "")
    return {word.casefold() for word in words if word.casefold() not in _DEDUPE_CONNECTORS}


def _split_list_lead_in(text):
    """Separa el conector de redacción (ej. "He trabajado con") del primer
    elemento real de una lista, para poder depurar ese elemento sin romper la frase.
    Solo busca "en"/"con" cerca del inicio, para no confundir preposiciones que son
    parte del propio término (ej. la "de" en "Gestión de Proyectos")."""
    words = text.split()
    search_window = min(5, len(words))
    last_connector_idx = None
    for index in range(search_window):
        if words[index].casefold() in ("en", "con"):
            last_connector_idx = index
    if last_connector_idx is not None and last_connector_idx < len(words) - 1:
        return " ".join(words[:last_connector_idx + 1]), " ".join(words[last_connector_idx + 1:])
    return "", text


def _dedupe_normalize(term):
    """Normaliza una palabra solo para comparar duplicados en el pulido final
    (quita acentos y plurales simples), sin afectar la validación anti-invención."""
    flattened = unicodedata.normalize("NFKD", term)
    flattened = "".join(ch for ch in flattened if not unicodedata.combining(ch))
    if len(flattened) > 5 and flattened.endswith("es"):
        flattened = flattened[:-2]
    elif len(flattened) > 4 and flattened.endswith("s"):
        flattened = flattened[:-1]
    return flattened


def _dedupe_terms(text):
    return {_dedupe_normalize(term) for term in _dedupe_words(text)}


def _join_list_naturally(items):
    """Une una lista de elementos como enumeración en español: coma entre los
    primeros y "y" antes del último (evita listas que terminan en seco con coma).
    Si el último elemento ya trae su propia conjunción "y" (frase ya natural),
    no se agrega una segunda para no duplicarla."""
    if len(items) <= 1:
        return ", ".join(items)
    if re.search(r"\by\b", items[-1], flags=re.IGNORECASE):
        return ", ".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def _final_text_cleanup(text):
    """Limpieza final segura: palabras contiguas repetidas y espacios/puntuación
    sobrantes que puedan quedar tras depurar redundancias."""
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r",\s*,+", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"\.\s*\.+", ".", text)
    return text.strip()


import re

def polish_summary_text(summary):
    """Revisa el resumen YA generado (por Ollama o por el fallback local) y elimina
    redundancias de redacción sin tocar hechos ni reglas de validación: si un término
    significativo ya fue mencionado antes en el texto (en cualquier oración anterior,
    incluyendo variantes de plural/acento), se quita su repetición posterior dentro
    de una lista separada por comas (ej. "...modelos predictivos..." y más adelante
    "...automatizaciones, Modelos Predictivos..." -> la segunda mención se depura).
    Solo quita duplicados COMPLETOS (todas sus palabras ya mencionadas antes); si un
    elemento aporta aunque sea una palabra nueva, se conserva para no perder información."""
    if not summary:
        return summary

    term_counts = {}

    def register_terms(terms):
        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1

    def dedupe_comma_list(match):
        items = [piece.strip() for piece in match.group(1).split(",")]
        lead = ""
        kept = []
        for index, item in enumerate(items):
            working_item = item
            if index == 0:
                lead, working_item = _split_list_lead_in(item)
            terms = _dedupe_terms(working_item)
            if not terms:
                kept.append(working_item)
                continue
            # Duplicado completo: todas las palabras del elemento ya se mencionaron
            # antes, por lo que no aporta información nueva.
            if all(term_counts.get(term, 0) > 0 for term in terms):
                continue
            register_terms(terms)
            kept.append(working_item)
        if lead:
            kept = [lead] if not kept else [f"{lead} {kept[0]}", *kept[1:]]
        return _join_list_naturally(kept) if kept else match.group(1)

    # Depura cada lista separada por comas dentro de cada oración, acumulando los
    # términos ya mencionados en oraciones anteriores del mismo resumen (incluso si
    # esa oración previa no tenía una lista con comas).
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    cleaned_sentences = []
    for sentence in sentences:
        cleaned = re.sub(r"([^.!?]*,[^.!?]*)", dedupe_comma_list, sentence, count=1)
        if "," not in sentence:
            # Sin comas no hay lista que depurar: igual se registran sus términos
            # para que oraciones futuras sepan que ya se mencionaron.
            register_terms(_dedupe_terms(sentence))
        cleaned_sentences.append(cleaned)

    result = " ".join(cleaned_sentences)

    # --- CORRECCIONES GRAMATICALES Y DE SINTAXIS ---
    # 1. Corrige la referencia a Freelance para que no lo trate como nombre de empresa ("En Consultor Freelance")
    result = re.sub(r'\bEn Consultor Freelance\b', 'Como consultor freelance', result, flags=re.IGNORECASE)
    result = re.sub(r'\bEn Freelance\b', 'Como freelance', result, flags=re.IGNORECASE)
    result = re.sub(r'\b(automatice|automatiqu[eé])\b', 'automaticé', result, flags=re.IGNORECASE)
    # 2. Correcciones ortográficas comunes de generación (ej. verbos en pretérito)
    result = re.sub(r'\bautomatice\b', 'automaticé', result, flags=re.IGNORECASE)

    # 3. Limpieza final de espacios dobles o residuales
    result = re.sub(r'\s+', ' ', result).strip()

    return _final_text_cleanup(result)


def build_local_summary(profile, offer_text, matched_skills, analysis=None):
    """Construye un resumen dinámico con datos del JSON cuando el modelo no responde."""
    dp = profile.get("datos_personales", {})
    profession = str(dp.get("profesion", "profesional")).strip()
    offer_lower = (offer_text or "").casefold()
    focus = []
    if "bi" in offer_lower or "business intelligence" in offer_lower:
        focus.append("análisis BI")
    if "data" in offer_lower or "datos" in offer_lower:
        focus.append("análisis de datos")
    if "automat" in offer_lower:
        focus.append("automatización")
    if "energia" in offer_lower or "energía" in offer_lower:
        focus.append("gestión energética")
    analyzed_level = str((analysis or {}).get("nivel_ajuste", "")).casefold()
    profile_text = json.dumps(profile, ensure_ascii=False).casefold()
    raw_priorities = [str(item) for item in (analysis or {}).get("palabras_clave", [])]
    # Las prioridades vienen del análisis de LA OFERTA, no del perfil: solo se aceptan
    # si todos sus términos relevantes están respaldados literalmente en el perfil maestro.
    analyzed_priorities = [
        item for item in raw_priorities
        if _significant_terms(item) and all(
            re.search(r"\b" + re.escape(term) + r"\b", profile_text)
            for term in _significant_terms(item)
        )
    ]
    junior_offer = analyzed_level == "junior" or any(term in offer_lower for term in ("junior", "recién egresado", "básico", "bajo supervisión", "inicial"))
    advanced_offer = analyzed_level == "avanzado" or any(term in offer_lower for term in ("analítica avanzada", "machine learning", "mlops", "producción", "inteligencia artificial", "modelos predictivos"))
    if junior_offer:
        focus.extend(["preparación y limpieza de datos", "análisis exploratorio", "documentación técnica"])
    elif advanced_offer:
        focus.extend(["modelado predictivo", "automatización analítica", "despliegue de soluciones de datos"])
    if analyzed_priorities:
        focus.extend(item for item in analyzed_priorities[:3] if item.casefold() not in {value.casefold() for value in focus})
    focus = [
        item for item in focus
        if not any(
            item.casefold() in other.casefold() and len(other) > len(item)
            for other in focus
        )
    ]
    skill_candidates = list(dict.fromkeys(
        str(item).strip() for item in matched_skills if str(item).strip()
    ))
    unique_skills = [
        skill for skill in skill_candidates
        if not any(
            len(skill.split()) == 1
            and re.search(r"\b" + re.escape(skill) + r"\b", other, flags=re.IGNORECASE)
            for other in skill_candidates
            if other.casefold() != skill.casefold()
        )
    ]
    focus_text = ", ".join(dict.fromkeys(focus)) or "optimización de procesos"
    skill_text = ", ".join(unique_skills[:6]) or "las competencias registradas"
    return (
        f"Soy {profession} y tengo experiencia en {focus_text}. He trabajado con {skill_text} "
        "en proyectos de datos e infraestructura eléctrica, participando en análisis, documentación "
        "y mejora de procesos. He integrado mi formación técnica con la experiencia profesional "
        "para transformar información en resultados útiles, mantener la trazabilidad y aportar "
        "soluciones prácticas a las necesidades del rol."
    )


def select_relevant_logros(profile, offer_text, proposed=None):
    """Selecciona logros por coincidencia con la oferta, no por posición en el JSON."""
    source = profile.get("logros", [])
    offer_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", offer_text or "")
    }
    proposed_map = {str(item).strip().casefold() for item in (proposed or [])}
    ranked = []
    for index, logro in enumerate(source):
        words = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", str(logro))
        score = sum(word.casefold() in offer_words for word in words)
        if str(logro).strip().casefold() in proposed_map:
            score += 3
        ranked.append((score, -index, logro))
    ranked.sort(reverse=True)
    return [item for score, _, item in ranked[:5] if score > 0] or source[:5]




def _priority_match_report(text, priorities):
    unique_priorities = list(dict.fromkeys(
        str(item).strip() for item in priorities if str(item).strip()
    ))
    text_terms = _significant_terms(text or "")
    matched = []
    unmatched = []
    for priority in unique_priorities:
        priority_terms = _significant_terms(priority)
        overlap = priority_terms & text_terms
        threshold = max(1, (len(priority_terms) + 1) // 2)
        (matched if len(overlap) >= threshold else unmatched).append(priority)
    total = len(unique_priorities)
    return {
        "porcentaje": round(len(matched) * 100 / total) if total else None,
        "coincidencias": len(matched),
        "requisitos": total,
    }


def _short_reason(reasons, max_length=90):
    if not reasons:
        return ""
    reason = str(reasons[0]).split(":", 1)[0].strip()
    return reason[:max_length]


def _match_label(report):
    if not report or report.get("porcentaje") is None:
        return "0/0 (N/D)"
    return f"{report.get('coincidencias', 0)}/{report.get('requisitos', 0)} ({report['porcentaje']}%)"


def adapt_profile_to_offer(profile, offer_text, analysis=None):
    """Adapta el resumen, prioridad de habilidades y experiencia a cualquier oferta sin inventar hechos."""
    offer_lower = (offer_text or "").lower()

    profile_skills = profile.get("habilidades", [])
    offer_terms = _significant_terms(offer_text or "")
    ranked_skills = sorted(
        [
            (
                int(str(skill).strip().casefold() in offer_lower),
                offer_lower.find(str(skill).strip().casefold())
                if str(skill).strip().casefold() in offer_lower
                else -len(_significant_terms(str(skill)) & offer_terms),
                index,
                skill,
            )
            for index, skill in enumerate(profile_skills)
        ],
        key=lambda item: (-item[0], item[1], item[2]),
    )
    matched_keywords = [skill for exact, relevance, _, skill in ranked_skills if exact or relevance < 0]

    def experience_end_year(experience, fallback_index):
        dates = str(experience.get("fechas", ""))
        years = re.findall(r"(?:19|20)\d{2}", dates)
        end_year = int(years[-1]) if years else 0
        return -end_year, fallback_index

    ordered_experience = [
        item for _, item in sorted(
            enumerate(profile.get("experiencia", [])),
            key=lambda pair: experience_end_year(pair[1], pair[0]),
        )
    ]

    summary = profile.get("perfil_profesional", {}).get("resumen", "")
    gemini_summary = str((analysis or {}).get("resumen_profesional", "")).strip()
    if (
        len(gemini_summary.split()) >= 60
        and gemini_summary != "NO_EVIDENCIADO"
        and summary_is_factual(gemini_summary, profile, offer_text)
    ):
        summary = gemini_summary
    else:
        gemini_summary = ""
        summary = build_local_summary(profile, offer_text, matched_keywords, analysis)
    summary_origin = (analysis or {}).get("resumen_origen")
    if not summary_origin:
        summary_origin = "ollama" if gemini_summary and summary == gemini_summary else "fallback_local"
    # Pulido de redundancia, aplicado sobre el resumen ya definitivo (venga de
    # Ollama o del fallback). Es local y no llama a Ollama, por lo que es seguro
    # para tests unitarios. La reescritura con Ollama (fluidez/sonoridad) se aplica
    # aparte, en el pipeline completo de generación (generate_cv_pdf_for_offer),
    # para no introducir llamadas de red dentro de esta función pura.
    summary = polish_summary_text(summary)
    gemini_keywords = []
    for suggestion in (analysis or {}).get("palabras_clave", []):
        suggestion_text = str(suggestion).strip()
        for skill in profile_skills:
            if suggestion_text.lower() in skill.lower() or skill.lower() in suggestion_text.lower():
                if skill not in gemini_keywords:
                    gemini_keywords.append(skill)

    final_keywords = []
    for keyword in gemini_keywords + matched_keywords:
        normalized_keyword = str(keyword).strip().casefold()
        if normalized_keyword and not any(normalized_keyword == existing.casefold() for existing in final_keywords):
            final_keywords.append(str(keyword).strip())

    profile_logros = profile.get("logros", [])
    selected_logros = select_relevant_logros(profile, offer_text, (analysis or {}).get("logros_priorizados", []))

    profile_responsibilities = [
        exp.get("descripcion", "") for exp in profile.get("experiencia", [])
    ]
    selected_responsibilities = [
        item for item in (analysis or {}).get("responsabilidades_priorizadas", [])
        if any(str(item).strip().lower() == str(real).strip().lower() for real in profile_responsibilities)
    ]

    return {
        "summary": summary,
        "summary_origin": summary_origin,
        "summary_match": _priority_match_report(summary, (analysis or {}).get("palabras_clave", [])),
        "summary_master_match": _priority_match_report(
            profile.get("perfil_profesional", {}).get("resumen", ""),
            (analysis or {}).get("palabras_clave", []),
        ),
        "keywords": final_keywords[:20],
        "experiencia": ordered_experience,
        "titulo_objetivo": (
            str((analysis or {}).get("cargo_detectado", "")).strip()
            if str((analysis or {}).get("cargo_detectado", "")).strip() not in {"", "NO_EVIDENCIADO", "No validado automáticamente"}
            else ""
        ),
        "logros": selected_logros[:5],
        "responsabilidades": selected_responsibilities[:8],
        "nivel_ajuste": (analysis or {}).get("nivel_ajuste", "No determinado"),
        "requisitos_no_evidenciados": (analysis or {}).get("requisitos_no_evidenciados", []),
    }


def generate_offer_report(offer_path, profile_path):
    profile = load_profile(profile_path)
    offer_text = extract_text_from_docx(offer_path)
    analysis = analyze_offer_and_profile(offer_text, profile)

    requirements = [
        item for item in analysis.get("palabras_clave", [])
        if isinstance(item, str) and item.strip()
    ]

    matches = classify_requirements(requirements, profile)
    validation = validate_claims_against_profile(
        requirements,
        profile,
    )

    return {
        "offer_text": offer_text,
        "analysis": analysis,
        "matching": matches,
        "validation": validation,
    }


def adapt_content_with_ollama(profile, offer_text, adapted, forbidden_companies=None):
    """Ejecuta adaptaciones separadas para resumen, experiencias y habilidades."""
    model_name = "qwen2.5:7b"
    adapted_experience = []
    experience_diagnostics = []
    for experience in adapted["experiencia"]:
        updated = dict(experience)
        diagnostic = {}
        updated["descripcion"] = adapt_experience_to_offer(
            experience, offer_text, model_name, forbidden_companies, diagnostics=diagnostic
        )
        adapted_experience.append(updated)
        diagnostic.setdefault("ollama_consultado", False)
        diagnostic.setdefault("ollama_respondio", False)
        diagnostic.setdefault("origen", "perfil_maestro")
        diagnostic.setdefault("motivo_fallback", ["no se recibió diagnóstico del adaptador"])
        diagnostic["ollama_aceptado"] = str(diagnostic["origen"]).startswith("ollama")
        diagnostic["porcentaje_uso_ollama"] = 100 if diagnostic["ollama_aceptado"] else 0
        experience_diagnostics.append({
            "empresa": experience.get("empresa", ""),
            "cargo": experience.get("cargo", ""),
            "origen": diagnostic["origen"],
            "uso_ollama_pct": diagnostic["porcentaje_uso_ollama"],
            "maestro_match": _match_label(_priority_match_report(
                experience.get("descripcion", ""), adapted.get("analysis_priorities", [])
            )),
            "final_match": _match_label(_priority_match_report(
                updated["descripcion"], adapted.get("analysis_priorities", [])
            )),
            "causa_fallback": _short_reason(diagnostic.get("motivo_fallback", [])),
        })

    skills_diagnostic = {}
    skills_result = adapt_skills_to_offer(profile, offer_text, model_name, diagnostics=skills_diagnostic)
    allowed = {
        str(item).strip().casefold(): str(item).strip()
        for item in (
            profile.get("aptitudes", [])
            + profile.get("software", [])
            + profile.get("nuevas_tecnologias", [])
            + profile.get("competencias", [])
            + profile.get("habilidades", [])
            + profile.get("certificaciones", [])
        )
        if str(item).strip()
    }
    def verified_items(items):
        selected = []
        if not isinstance(items, list):
            return selected
        for item in items:
            verified = allowed.get(str(item).strip().casefold())
            if verified and verified not in selected:
                selected.append(verified)
        return selected

    offer_terms = _significant_terms(offer_text)

    def relevant_items(items):
        ranked = []
        for index, item in enumerate(items):
            item_text = str(item).strip()
            exact_match = item_text.casefold() in offer_text.casefold()
            score = len(_significant_terms(item_text) & offer_terms)
            if exact_match or score:
                ranked.append((score, index, item))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        return [item for _, _, item in ranked]

    selected_aptitudes = relevant_items(verified_items(skills_result.get("aptitudes_clave", [])))
    selected_tools = relevant_items(verified_items(skills_result.get("herramientas", [])))
    selected_competencies = relevant_items(verified_items(skills_result.get("competencias", [])))
    matched_aptitudes = list(selected_aptitudes)
    matched_tools = list(selected_tools)
    matched_competencies = list(selected_competencies)
    aptitude_source = profile.get("aptitudes", [])
    software_source = profile.get("software", [])
    competency_source = profile.get("competencias", [])
    new_technology_source = profile.get("nuevas_tecnologias", [])
    selected_new_technologies = [
        item for item in verified_items(skills_result.get("nuevas_tecnologias", []))
        if item in relevant_items(new_technology_source)
    ]

    def fill_from_master(selected, source, minimum=5):
        ordered_source = relevant_items(source) + [
            item for item in source if item not in relevant_items(source)
        ]
        for item in ordered_source:
            if item not in selected:
                selected.append(item)
            if len(selected) >= minimum:
                break
        return selected

    selected_aptitudes = fill_from_master(selected_aptitudes, aptitude_source)
    selected_tools = fill_from_master(selected_tools, software_source, minimum=8)
    selected_competencies = fill_from_master(
        selected_competencies, competency_source, minimum=6
    )
    selected_new_technologies = fill_from_master(selected_new_technologies, new_technology_source)
    selected_skills = []
    for item in matched_aptitudes + matched_tools + matched_competencies:
        verified = allowed.get(str(item).strip().casefold())
        if verified and verified not in selected_skills:
            selected_skills.append(verified)

    skill_source = (
        profile.get("aptitudes", [])
        + profile.get("software", [])
        + profile.get("competencias", [])
        + profile.get("habilidades", [])
    )
    for skill in relevant_items(skill_source):
        if skill not in selected_skills:
            selected_skills.append(skill)
        if len(selected_skills) >= 14:
            break
    adapted["keywords"] = selected_skills
    adapted["aptitudes"] = selected_aptitudes
    adapted["software"] = selected_tools
    adapted["nuevas_tecnologias"] = selected_new_technologies
    adapted["competencias"] = selected_competencies

    source_logros = profile.get("logros", [])
    proposed_logros = skills_result.get("logros", [])
    selected_logros = select_relevant_logros(profile, offer_text, proposed_logros)
    if selected_logros:
        adapted["logros"] = selected_logros[:5]
    adapted["experiencia"] = adapted_experience
    proposed_skills = {
        str(item).strip().casefold()
        for key in ("aptitudes_clave", "herramientas", "nuevas_tecnologias", "competencias")
        for item in (
            skills_result.get(key, [])
            if isinstance(skills_result.get(key, []), list)
            else []
        )
    }
    accepted_skills = [item for item in selected_skills if item.casefold() in proposed_skills]
    skills_diagnostic = {
        "origen": "ollama" if accepted_skills else "perfil_maestro",
        "uso_ollama_pct": round(
            len(accepted_skills) * 100 / skills_diagnostic["elementos_habilidad_propuestos"]
        ) if skills_diagnostic.get("elementos_habilidad_propuestos", 0) else 0,
        "habilidades_propuestas": skills_diagnostic.get("elementos_habilidad_propuestos", 0),
        "habilidades_coincidentes": len(accepted_skills),
        "prioridades_coincidentes": _match_label(_priority_match_report(
            " ".join(selected_skills), adapted.get("analysis_priorities", [])
        )),
    }
    summary_diagnostic = {
        "origen": adapted.get("summary_origin", "fallback_local"),
        "uso_ollama_pct": 100 if str(adapted.get("summary_origin", "")).startswith("ollama") else 0,
        "intentos": len((adapted.get("analysis") or {}).get("resumen_intentos", [])),
        "causa_fallback": _short_reason([
            reason
            for attempt in (adapted.get("analysis") or {}).get("resumen_intentos", [])
            for reason in attempt.get("motivos_rechazo", [])
        ]),
        "maestro_match": _match_label(adapted.get("summary_master_match", {})),
        "oferta_match": _match_label(adapted.get("summary_match", {})),
    }
    analysis_diagnostic = {
        "ollama_respondio": bool((adapted.get("analysis") or {}).get("analisis_oferta_ollama_respondio")),
        "origen": (adapted.get("analysis") or {}).get("analisis_oferta_origen", "desconocido"),
        "prioridades_detectadas": len(adapted.get("analysis_priorities", [])),
    }
    ollama_blocks = [analysis_diagnostic, summary_diagnostic, *experience_diagnostics, skills_diagnostic]
    adapted["reporte_adaptacion"] = {
        "analisis_oferta": analysis_diagnostic,
        "perfil": summary_diagnostic,
        "experiencias": experience_diagnostics,
        "habilidades": skills_diagnostic,
        "totales": {
            "bloques": len(ollama_blocks),
            "ollama_aceptado": sum(str(block.get("origen", "")).startswith("ollama") for block in ollama_blocks),
            "fallback": sum(str(block.get("origen", "")).startswith(("fallback", "perfil_maestro")) for block in ollama_blocks),
            "porcentaje_bloques_ollama_aceptados": round(
                sum(str(block.get("origen", "")).startswith("ollama") for block in ollama_blocks)
                * 100 / len(ollama_blocks)
            ) if ollama_blocks else 0,
        },
    }
    adapted["bloques_ollama"] = adapted["reporte_adaptacion"]["totales"]["ollama_aceptado"]
    return adapted


def generate_cv_pdf_for_offer(offer_name=None, offers_dir=None, profile_path=None, output_dir=None):
    root = Path(__file__).resolve().parent.parent
    if offers_dir is None:
        offers_dir = root / "ofertas"
    if output_dir is None:
        output_dir = root / "output" / "pdf"
    if profile_path is None:
        profile_path = root / "config" / "perfil_maestro.json"

    offer_files = sorted(Path(offers_dir).glob("*.docx")) if offer_name is None else [Path(offers_dir) / offer_name]
    if not offer_files:
        raise FileNotFoundError(f"No hay ofertas .docx en: {offers_dir}")
    offer_path = offer_files[0]
    offer_name = offer_path.name

    if not offer_path.exists():
        raise FileNotFoundError(f"No existe la oferta: {offer_path}")

    profile = load_profile(str(profile_path))
    offer_text = extract_text_from_docx(str(offer_path))
    analysis = analyze_offer_and_profile(offer_text, profile)
    adapted = adapt_profile_to_offer(profile, offer_text, analysis)
    adapted["analysis"] = analysis
    adapted["analysis_priorities"] = analysis.get("palabras_clave", [])
    forbidden_companies = extract_offer_organizations(offer_text, offer_name)
    adapted = adapt_content_with_ollama(profile, offer_text, adapted, forbidden_companies)
    # Reescritura final con Ollama: mejora fluidez/sonoridad del resumen ya aceptado,
    # sin recortar información (resguardo de longitud) ni inventar datos (resguardo
    # de veracidad). Si falla o recorta de más, se conserva el resumen tal como estaba.
    adapted["summary"] = polish_text_with_ollama(adapted["summary"], profile=profile, offer_text=offer_text)
    analysis["bloques_adaptados"] = adapted.get("bloques_ollama", 0)
    analysis["reporte_adaptacion"] = adapted.get("reporte_adaptacion", {})

    html = build_cv_html(
        {
            "perfil_profesional": {"resumen": adapted["summary"]},
            "habilidades": adapted["keywords"],
            "aptitudes": adapted.get("aptitudes", []),
            "software": adapted.get("software", []),
            "nuevas_tecnologias": adapted.get("nuevas_tecnologias", []),
            "competencias": adapted.get("competencias", []),
            "habilidades_blandas": profile.get("habilidades_blandas", []),
            "experiencia": adapted["experiencia"],
            "formacion": profile.get("formacion", []),
            "logros": adapted["logros"],
            "titulo_objetivo": adapted["titulo_objetivo"],
        },
        {
            **profile,
            "perfil_profesional": {"resumen": adapted["summary"]},
        },
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"CV_Anderson_Sarmiento_{Path(offer_name).stem}.pdf"
    render_cv_to_pdf_model(html, str(pdf_path))

    return {
        "pdf": str(pdf_path),
        "analysis": analysis,
        "adapted": adapted,
        "reporte_adaptacion": adapted.get("reporte_adaptacion", {}),
    }


def generate_all_cv_for_offers(offers_dir=None, profile_path=None, output_dir=None):
    root = Path(__file__).resolve().parent.parent
    if offers_dir is None:
        offers_dir = root / "ofertas"
    if profile_path is None:
        profile_path = root / "config" / "perfil_maestro.json"
    if output_dir is None:
        output_dir = root / "output" / "pdf"

    results = []
    for offer_file in sorted(Path(offers_dir).glob("*.docx")):
        result = generate_cv_pdf_for_offer(
            offer_name=offer_file.name,
            offers_dir=str(offers_dir),
            profile_path=str(profile_path),
            output_dir=str(output_dir),
        )
        results.append(result)
    return results


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    profile_path = root / "config" / "perfil_maestro.json"
    offers_dir = root / "ofertas"
    output_dir = root / "output" / "pdf"

    offers = sorted(Path(offers_dir).glob("*.docx"))
    if not offers:
        print("No se encontraron ofertas en la carpeta ofertas/.")
    else:
        generated_items = generate_all_cv_for_offers(str(offers_dir), str(profile_path), str(output_dir))
        for item in generated_items:
            analysis = item["analysis"]

            # --- DEPURACIÓN (borrar después) ---
            import src.llm.gemini as gem
            print("\n===== INTENTOS DEL RESUMEN =====")
            print(json.dumps(analysis.get("resumen_intentos"), ensure_ascii=False, indent=2))
            print("\n===== ÚLTIMO ERROR DE OLLAMA =====")
            print(gem._LAST_OLLAMA_ERROR or "(ninguno)")
            print("\n===== REPORTE DEL PULIDO =====")
            print(json.dumps(gem._LAST_POLISH_REPORT, ensure_ascii=False, indent=2))
            print("=================================\n")
            # -----------------------------------

            print(json.dumps({
                "pdf": item["pdf"],
                "cargo": analysis.get("cargo_detectado"),
                "analisis": analysis.get("estado"),
                "modelo": analysis.get("modelo"),
                "resumen_origen": analysis.get("resumen_origen"),
                "motivo": analysis.get("motivo"),

                "nivel_ajuste": analysis.get("nivel_ajuste"),
                "palabras_clave": len(analysis.get("palabras_clave", [])),
                "bloques_adaptados_ollama": analysis.get("bloques_adaptados", 0),
                "reporte_adaptacion": analysis.get("reporte_adaptacion", {}),
            }, ensure_ascii=False, indent=2))