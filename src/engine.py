import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction.word_reader import extract_text_from_docx
from src.llm.llm import (
    adapt_experiences_and_skills,
    analyze_offer_and_profile,
    offer_requirements,
    summary_is_factual,
    _ECHO_STEM,
    _significant_terms,
    _stem,
    _stems_of,
)
from src.llm.polish import polish_with_gemini
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


def clean_summary_text(text):
    """Limpieza local simple del resumen: espacios, puntuación y palabras contiguas
    repetidas. Además, el trabajo freelance nunca se presenta como una empresa."""
    if not text:
        return text
    text = re.sub(r"\bEn Consultor Freelance\b", "Como consultor freelance", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEn Freelance\b", "Como freelance", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r",\s*,+", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"\.\s*\.+", ".", text)
    return text.strip()


def shorten_by_sentences(text, max_words=110):
    """Primeras oraciones completas del texto sin pasar de max_words (al menos una)."""
    sentences = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    kept = []
    for sentence in sentences:
        if kept and len(" ".join(kept + [sentence]).split()) > max_words:
            break
        kept.append(sentence)
    return " ".join(kept).strip()


def select_logros_for_cv(profile, offer_text, experiences):
    """Logros destacados (mínimo 4, máximo 5): primero los que tienen relación con la oferta
    y no repiten las experiencias mostradas; luego se completa con los demás logros del
    perfil, empezando por los que menos repiten lo que ya dicen las experiencias."""
    experience_text = re.sub(r"(\d)\s+%", r"\1%", " ".join(str(item.get("descripcion", "")) for item in experiences))
    experience_terms = _significant_terms(experience_text)
    experience_stems = _stems_of(experience_text, _ECHO_STEM)
    all_logros = [re.sub(r"(\d)\s+%", r"\1%", str(logro)).strip() for logro in profile.get("logros", [])]
    # Palabras exclusivas de cada logro (no aparecen en ningún otro): nombran su proyecto.
    stems_per_logro = [{_stem(term, _ECHO_STEM) for term in _significant_terms(logro)} for logro in all_logros]
    exclusive = {
        logro: {stem for stem in stems if sum(stem in other for other in stems_per_logro) == 1}
        for logro, stems in zip(all_logros, stems_per_logro)
    }

    def overlap(logro):
        numbers = re.findall(r"\d+(?:[.,]\d+)?%", logro)
        if numbers and all(number in experience_text for number in numbers):
            return 1.0
        # Mismo proyecto ya contado en una experiencia (p. ej., "apuestas deportivas").
        if len(exclusive.get(logro, set()) & experience_stems) >= 2:
            return 1.0
        terms = _significant_terms(logro)
        return len(terms & experience_terms) / len(terms) if terms else 1.0

    fresh_logros = [logro for logro in all_logros if overlap(logro) < 0.6]
    offer_words = {word.casefold() for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", offer_text or "")}
    selected = [
        logro for logro in select_relevant_logros({"logros": fresh_logros}, offer_text)
        if any(word.casefold() in offer_words for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", logro))
    ][:5]
    for logro in sorted(all_logros, key=overlap):
        if len(selected) >= 4:
            break
        if logro not in selected:
            selected.append(logro)
    return selected


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

    # Si el resumen del modelo no pasa la validación, se usan las primeras oraciones
    # completas del resumen del perfil maestro (un perfil de CV no debe ser largo).
    summary = shorten_by_sentences(profile.get("perfil_profesional", {}).get("resumen", ""))
    llm_summary = str((analysis or {}).get("resumen_profesional", "")).strip()
    llm_accepted = (
        len(llm_summary.split()) >= 60
        and llm_summary != "NO_EVIDENCIADO"
        and summary_is_factual(
            llm_summary, profile, offer_text,
            requirements=offer_requirements(analysis) if (analysis or {}).get("analisis_oferta_llm_respondio") else None,
        )
    )
    if llm_accepted:
        summary = llm_summary
    summary_origin = (analysis or {}).get("resumen_origen") or ("llm" if llm_accepted else "fallback_local")
    summary = clean_summary_text(summary)
    llm_keywords = []
    for suggestion in (analysis or {}).get("palabras_clave", []):
        suggestion_text = str(suggestion).strip()
        for skill in profile_skills:
            if suggestion_text.lower() in skill.lower() or skill.lower() in suggestion_text.lower():
                if skill not in llm_keywords:
                    llm_keywords.append(skill)

    final_keywords = []
    for keyword in llm_keywords + matched_keywords:
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


def adapt_content_with_llm(profile, offer_text, adapted, forbidden_companies=None):
    """Adapta experiencias y habilidades en una sola llamada y arma el reporte."""
    llm_result = adapt_experiences_and_skills(
        profile, adapted["experiencia"], offer_text, forbidden_companies
    )
    adapted_experience = []
    experience_diagnostics = []
    for experience, description, diagnostic in zip(
        adapted["experiencia"], llm_result["descripciones"], llm_result["diagnosticos"]
    ):
        updated = dict(experience)
        updated["descripcion"] = description
        adapted_experience.append(updated)
        experience_diagnostics.append({
            "empresa": experience.get("empresa", ""),
            "cargo": experience.get("cargo", ""),
            "origen": diagnostic["origen"],
            "uso_llm_pct": 100 if str(diagnostic["origen"]).startswith("llm") else 0,
            "intentos": diagnostic.get("intentos", 1),
            "maestro_match": _match_label(_priority_match_report(
                experience.get("descripcion", ""), adapted.get("analysis_priorities", [])
            )),
            "final_match": _match_label(_priority_match_report(
                updated["descripcion"], adapted.get("analysis_priorities", [])
            )),
            "causa_fallback": _short_reason(diagnostic.get("motivo_fallback", [])),
            "motivos_completos": diagnostic.get("motivo_fallback", []),
            "texto_propuesto": diagnostic.get("texto_propuesto", ""),
        })

    skills_diagnostic = llm_result["diagnostico_habilidades"]
    skills_result = llm_result["habilidades"]
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

    # Para que la barra lateral coincida con el texto del CV, después de lo que pide la
    # oferta se priorizan los elementos que el propio CV menciona (primero el perfil
    # profesional, luego las experiencias) y al final el resto en el orden del perfil.
    summary_stems = _stems_of(adapted.get("summary", ""))
    experience_stems = _stems_of(" ".join(str(item.get("descripcion", "")) for item in adapted_experience))

    def mention_rank(item):
        stems = _stems_of(str(item))
        if not stems:
            return 2
        if len(stems & summary_stems) / len(stems) >= 0.5:
            return 0
        if len(stems & experience_stems) / len(stems) >= 0.5:
            return 1
        return 2

    def near_duplicate(item, others):
        """Casi duplicado: todas las palabras de uno están contenidas en el otro
        (p. ej. "Power BI" y "Visualización Power BI")."""
        stems = _stems_of(str(item))
        for other in others:
            other_stems = _stems_of(str(other))
            if stems and other_stems and (stems <= other_stems or other_stems <= stems):
                return True
        return False

    def fill_from_master(selected, source, minimum=5, model_choice=()):
        relevant = relevant_items(source)
        chosen = [item for item in model_choice if item in source and item not in relevant]
        rest = sorted((item for item in source if item not in relevant and item not in chosen), key=mention_rank)
        for item in relevant + chosen + rest:
            if len(selected) >= minimum:
                break
            if item not in selected and not near_duplicate(item, selected):
                selected.append(item)
        return selected

    selected_aptitudes = fill_from_master(
        selected_aptitudes, aptitude_source, model_choice=verified_items(skills_result.get("aptitudes_clave", []))
    )
    selected_tools = fill_from_master(
        selected_tools, software_source, minimum=8, model_choice=verified_items(skills_result.get("herramientas", []))
    )
    selected_competencies = fill_from_master(
        selected_competencies, competency_source, minimum=6,
        model_choice=verified_items(skills_result.get("competencias", [])),
    )
    selected_new_technologies = fill_from_master(
        selected_new_technologies, new_technology_source,
        model_choice=verified_items(skills_result.get("nuevas_tecnologias", [])),
    )
    selected_skills = []
    for item in matched_aptitudes + matched_tools + matched_competencies:
        verified = allowed.get(str(item).strip().casefold())
        if verified and verified not in selected_skills and not near_duplicate(verified, selected_skills):
            selected_skills.append(verified)

    skill_source = (
        profile.get("aptitudes", [])
        + profile.get("software", [])
        + profile.get("competencias", [])
        + profile.get("habilidades", [])
    )
    for skill in relevant_items(skill_source):
        if skill not in selected_skills and not near_duplicate(skill, selected_skills):
            selected_skills.append(skill)
        if len(selected_skills) >= 14:
            break
    adapted["keywords"] = selected_skills
    adapted["aptitudes"] = selected_aptitudes
    adapted["software"] = selected_tools
    adapted["nuevas_tecnologias"] = selected_new_technologies
    adapted["competencias"] = selected_competencies

    adapted["logros"] = select_logros_for_cv(profile, offer_text, adapted_experience)
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
        "origen": "llm" if accepted_skills else "perfil_maestro",
        "uso_llm_pct": round(
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
        "uso_llm_pct": 100 if str(adapted.get("summary_origin", "")).startswith("llm") else 0,
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
        "llm_respondio": bool((adapted.get("analysis") or {}).get("analisis_oferta_llm_respondio")),
        "origen": (adapted.get("analysis") or {}).get("analisis_oferta_origen", "desconocido"),
        "prioridades_detectadas": len(adapted.get("analysis_priorities", [])),
    }
    llm_blocks = [analysis_diagnostic, summary_diagnostic, *experience_diagnostics, skills_diagnostic]
    accepted_blocks = sum(str(block.get("origen", "")).startswith("llm") for block in llm_blocks)
    adapted["reporte_adaptacion"] = {
        "analisis_oferta": analysis_diagnostic,
        "perfil": summary_diagnostic,
        "experiencias": experience_diagnostics,
        "habilidades": skills_diagnostic,
        "totales": {
            "bloques": len(llm_blocks),
            "llm_aceptado": accepted_blocks,
            "fallback": sum(str(block.get("origen", "")).startswith(("fallback", "perfil_maestro")) for block in llm_blocks),
            "porcentaje_bloques_llm_aceptados": round(accepted_blocks * 100 / len(llm_blocks)) if llm_blocks else 0,
        },
    }
    adapted["bloques_llm"] = accepted_blocks
    return adapted


class GeminiIncomplete(RuntimeError):
    """Gemini no redactó el perfil y todas las experiencias; no se genera el PDF."""


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
    adapted = adapt_content_with_llm(profile, offer_text, adapted, forbidden_companies)
    # Redacción final con Gemini: un prompt para el perfil y otro para las experiencias.
    unevidenced = analysis.get("requisitos_no_evidenciados", []) if analysis.get("analisis_oferta_llm_respondio") else []
    summary, descriptions, polish_report = polish_with_gemini(
        adapted["summary"], adapted["experiencia"], adapted["analysis_priorities"], profile, offer_text, unevidenced
    )
    adapted["summary"] = clean_summary_text(summary)
    adapted["experiencia"] = [
        {**experience, "descripcion": description}
        for experience, description in zip(adapted["experiencia"], descriptions)
    ]
    # Los logros se eligen otra vez con los textos finales de Gemini, para que no repitan
    # lo que ahora dicen las experiencias.
    adapted["logros"] = select_logros_for_cv(profile, offer_text, adapted["experiencia"])
    adapted.setdefault("reporte_adaptacion", {})["pulido_gemini"] = polish_report
    if polish_report.get("perfil") or polish_report.get("experiencias"):
        print(
            f"Gemini: perfil con {polish_report.get('perfil') or 'ninguno'}; "
            f"experiencias con {polish_report.get('experiencias') or 'ninguno'}",
            file=sys.stderr,
        )
    for notice in polish_report.get("avisos", []):
        print(f"AVISO Gemini: {notice}", file=sys.stderr)
    # El texto final siempre debe ser de Gemini: sin él no se genera un CV redactado por Groq.
    if polish_report.get("estado") != "desactivado" and not polish_report.get("completo"):
        raise GeminiIncomplete(
            "Gemini no redactó todo el CV; no se generó el PDF para no dejar texto de Groq. "
            "Intenta más tarde (el cupo gratuito se reinicia a las 2:00 a. m. hora de Colombia). "
            "Detalle: " + " | ".join(polish_report.get("avisos", []))
        )
    analysis["bloques_adaptados"] = adapted.get("bloques_llm", 0)
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
        try:
            generated_items = generate_all_cv_for_offers(str(offers_dir), str(profile_path), str(output_dir))
        except GeminiIncomplete as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        for item in generated_items:
            analysis = item["analysis"]
            print(json.dumps({
                "pdf": item["pdf"],
                "cargo": analysis.get("cargo_detectado"),
                "analisis": analysis.get("estado"),
                "modelo": analysis.get("modelo"),
                "resumen_origen": analysis.get("resumen_origen"),
                "motivo": analysis.get("motivo"),
                "resumen_intentos": analysis.get("resumen_intentos", []),

                "nivel_ajuste": analysis.get("nivel_ajuste"),
                "palabras_clave": len(analysis.get("palabras_clave", [])),
                "bloques_adaptados_llm": analysis.get("bloques_adaptados", 0),
                "reporte_adaptacion": analysis.get("reporte_adaptacion", {}),
            }, ensure_ascii=False, indent=2))