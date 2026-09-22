import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction.word_reader import extract_text_from_docx
from src.llm.gemini import adapt_achievements_to_offer, adapt_experience_to_offer, adapt_skills_to_offer, analyze_offer_and_profile
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


def adapt_profile_to_offer(profile, offer_text, analysis=None):
    """Adapta el resumen, prioridad de habilidades y experiencia a cualquier oferta sin inventar hechos."""
    offer_lower = (offer_text or "").lower()

    profile_skills = profile.get("habilidades", [])
    matched_keywords = []
    for skill in profile_skills:
        skill_lower = skill.lower()
        if skill_lower in offer_lower or any(token.lower() in offer_lower for token in skill.split()):
            matched_keywords.append(skill)

    if not matched_keywords:
        matched_keywords = profile_skills[:10]

    def experience_start_year(experience, fallback_index):
        dates = str(experience.get("fechas", ""))
        match = re.search(r"(?:19|20)\d{2}", dates)
        if match:
            return 0, -int(match.group(0)), fallback_index
        experience_text = " ".join(str(value) for value in experience.values()).lower()
        relevance = sum(1 for token in offer_lower.split() if len(token) > 3 and token in experience_text)
        return 1, -relevance, fallback_index

    ordered_experience = [
        item for _, item in sorted(
            enumerate(profile.get("experiencia", [])),
            key=lambda pair: experience_start_year(pair[1], pair[0]),
        )
    ]

    summary = profile.get("perfil_profesional", {}).get("resumen", "")
    gemini_summary = str((analysis or {}).get("resumen_profesional", "")).strip()
    if len(gemini_summary.split()) >= 80 and gemini_summary != "NO_EVIDENCIADO":
        summary = gemini_summary
    else:
        gemini_summary = ""
    tokens = {
        "data": ["data scientist", "cientifico de datos", "científico de datos", "data analyst", "analista de datos", "analytics", "data"],
        "bi": ["business intelligence", "bi", "power bi", "dashboard", "dashboards", "analista bi"],
        "energia": ["energia", "energía", "eficiencia energética", "iso 50001", "movilidad eléctrica", "energy"],
        "ingenieria": ["ingeniero eléctrico", "ingenieria electrica", "ingeniería eléctrica", "project manager", "mantenimiento eléctrico"],
        "automatizacion": ["automatización", "automatizacion", "python", "etl", "sql"],
    }

    if not gemini_summary and any(token in offer_lower for token in tokens["data"]):
        summary = (
            "Ingeniero eléctrico con enfoque en análisis de datos, automatización, visualización y modelado predictivo. "
            "Cuenta con experiencia en Python, Power BI, SQL, ETL y análisis exploratorio para convertir datos complejos en información útil para la toma de decisiones. "
            "Su perfil combina ingeniería, análisis de información y eficiencia operativa, con especial interés en soluciones basadas en datos y optimización de procesos."
        )
    elif not gemini_summary and any(token in offer_lower for token in tokens["bi"]):
        summary = (
            "Ingeniero eléctrico y analista de datos con experiencia en BI, ETL, Power BI, SQL, automatización y visualización de indicadores. "
            "Aplica análisis exploratorio, KPIs y transformación de datos para optimizar decisiones operativas y energéticas."
        )
    elif not gemini_summary and any(token in offer_lower for token in tokens["energia"]):
        summary = (
            "Ingeniero eléctrico con experiencia en análisis energético, eficiencia y optimización de procesos. "
            "Ha trabajado en automatización, gestión energética, indicadores operativos y soluciones de análisis para infraestructura y movilidad eléctrica."
        )
    elif not gemini_summary and any(token in offer_lower for token in tokens["ingenieria"]):
        summary = (
            "Ingeniero eléctrico con experiencia en infraestructura, automatización, mantenimiento, coordinación técnica y gestión de proyectos. "
            "Cuenta con desempeño en sistemas eléctricos, indicadores operativos, proyectos energéticos y optimización de procesos."
        )
    elif not gemini_summary and any(token in offer_lower for token in tokens["automatizacion"]):
        summary = (
            "Ingeniero eléctrico con experiencia en automatización, ETL, Power BI y optimización de procesos. "
            "Aplica Python, análisis de datos y automatización para mejorar la operación, la trazabilidad y la toma de decisiones."
        )

    preferred_order = [
        "Python",
        "SQL",
        "Power BI",
        "ETL",
        "Machine Learning",
        "Pandas",
        "PostgreSQL",
        "ISO 50001",
        "Movilidad eléctrica",
        "Automatización",
        "Análisis de datos",
        "Visualización de datos",
    ]
    ordered_keywords = [
        item for item in preferred_order
        if any(item.lower() in skill.lower() for skill in profile_skills)
    ]

    gemini_keywords = []
    for suggestion in (analysis or {}).get("palabras_clave", []):
        suggestion_text = str(suggestion).strip()
        for skill in profile_skills:
            if suggestion_text.lower() in skill.lower() or skill.lower() in suggestion_text.lower():
                if skill not in gemini_keywords:
                    gemini_keywords.append(skill)

    final_keywords = []
    for keyword in gemini_keywords + matched_keywords + ordered_keywords:
        normalized_keyword = str(keyword).strip().casefold()
        if normalized_keyword and not any(normalized_keyword == existing.casefold() for existing in final_keywords):
            final_keywords.append(str(keyword).strip())

    profile_logros = profile.get("logros", [])
    selected_logros = [
        logro for logro in (analysis or {}).get("logros_priorizados", [])
        if any(str(logro).strip().lower() == str(real).strip().lower() for real in profile_logros)
    ]
    if not selected_logros:
        selected_logros = profile_logros

    profile_responsibilities = [
        exp.get("descripcion", "") for exp in profile.get("experiencia", [])
    ]
    selected_responsibilities = [
        item for item in (analysis or {}).get("responsabilidades_priorizadas", [])
        if any(str(item).strip().lower() == str(real).strip().lower() for real in profile_responsibilities)
    ]

    return {
        "summary": summary,
        "keywords": final_keywords[:20],
        "experiencia": ordered_experience[:4],
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
        "Python",
        "Power BI",
        "SQL",
        "ETL",
        "Machine Learning",
        "ISO 50001",
        "Movilidad eléctrica",
        "TensorFlow",
    ]

    matches = classify_requirements(requirements, profile)
    validation = validate_claims_against_profile([
        "Python",
        "Power BI",
        "Científico de Datos en Green Mobil",
        "TensorFlow",
    ], profile)

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
    for experience in adapted["experiencia"]:
        updated = dict(experience)
        updated["descripcion"] = adapt_experience_to_offer(
            experience, offer_text, model_name, forbidden_companies
        )
        adapted_experience.append(updated)

    skills_result = adapt_skills_to_offer(profile, offer_text, model_name)
    allowed = {
        str(item).strip().casefold(): str(item).strip()
        for item in profile.get("habilidades", []) + profile.get("certificaciones", [])
        if str(item).strip()
    }
    selected_skills = []
    for item in skills_result.get("aptitudes_clave", []) + skills_result.get("herramientas", []):
        verified = allowed.get(str(item).strip().casefold())
        if verified and verified not in selected_skills:
            selected_skills.append(verified)

    if selected_skills:
        adapted["keywords"] = selected_skills

    source_logros = profile.get("logros", [])
    proposed_logros = adapt_achievements_to_offer(source_logros, offer_text, model_name)
    source_by_text = {str(item).strip().casefold(): item for item in source_logros}
    selected_logros = [
        source_by_text[item.casefold()]
        for item in proposed_logros
        if item.casefold() in source_by_text
    ]
    if selected_logros:
        adapted["logros"] = selected_logros[:5]
    adapted["experiencia"] = adapted_experience
    adapted["bloques_ollama"] = len(adapted_experience) + 2
    return adapted


def generate_cv_pdf_for_offer(offer_name: str = "RapiCredit_Científico de Datos Junior.docx", offers_dir=None, profile_path=None, output_dir=None):
    root = Path(__file__).resolve().parent.parent
    if offers_dir is None:
        offers_dir = root / "ofertas"
    if output_dir is None:
        output_dir = root / "output" / "pdf"
    if profile_path is None:
        profile_path = root / "config" / "perfil_maestro.json"

    offer_path = Path(offers_dir) / offer_name

    if not offer_path.exists():
        raise FileNotFoundError(f"No existe la oferta: {offer_path}")

    profile = load_profile(str(profile_path))
    offer_text = extract_text_from_docx(str(offer_path))
    analysis = analyze_offer_and_profile(offer_text, profile)
    adapted = adapt_profile_to_offer(profile, offer_text, analysis)
    forbidden_companies = extract_offer_organizations(offer_text, offer_name)
    adapted = adapt_content_with_ollama(profile, offer_text, adapted, forbidden_companies)
    analysis["bloques_adaptados"] = adapted.get("bloques_ollama", 0)

    html = build_cv_html(
        {
            "perfil_profesional": {"resumen": adapted["summary"]},
            "habilidades": adapted["keywords"],
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
            print(json.dumps({
                "pdf": item["pdf"],
                "cargo": analysis.get("cargo_detectado"),
                "analisis": analysis.get("estado"),
                "modelo": analysis.get("modelo"),
                "motivo": analysis.get("motivo"),
                "nivel_ajuste": analysis.get("nivel_ajuste"),
                "palabras_clave": len(analysis.get("palabras_clave", [])),
                "bloques_adaptados_ollama": analysis.get("bloques_adaptados", 0),
            }, ensure_ascii=False, indent=2))
