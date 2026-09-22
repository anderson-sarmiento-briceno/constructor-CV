import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction.word_reader import extract_text_from_docx
from src.llm.gemini import analyze_offer_and_profile
from src.matching.matcher import classify_requirements
from src.rendering.pdf_renderer import build_cv_html, render_cv_to_pdf_model
from src.validation.validation import validate_claims_against_profile


def load_profile(profile_path):
    with open(profile_path, "r", encoding="utf-8") as file:
        return json.load(file)


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

    experience_order = {
        "Green Mobil": 0,
        "Enel Colombia": 1,
        "Enel": 1,
        "Consultor Freelance": 2,
    }
    gemini_experience = (analysis or {}).get("experiencia_priorizada", [])
    for index, suggestion in enumerate(gemini_experience):
        suggestion_lower = str(suggestion).lower()
        for experience in profile.get("experiencia", []):
            company = str(experience.get("empresa", ""))
            role = str(experience.get("cargo", ""))
            if company.lower() in suggestion_lower or role.lower() in suggestion_lower:
                experience_order[company] = index
    ordered_experience = sorted(
        profile.get("experiencia", []),
        key=lambda exp: experience_order.get(exp.get("empresa", ""), 99),
    )

    summary = profile.get("perfil_profesional", {}).get("resumen", "")
    tokens = {
        "data": ["data scientist", "cientifico de datos", "científico de datos", "data analyst", "analista de datos", "analytics", "data"],
        "bi": ["business intelligence", "bi", "power bi", "dashboard", "dashboards", "analista bi"],
        "energia": ["energia", "energía", "eficiencia energética", "iso 50001", "movilidad eléctrica", "energy"],
        "ingenieria": ["ingeniero eléctrico", "ingenieria electrica", "ingeniería eléctrica", "project manager", "mantenimiento eléctrico"],
        "automatizacion": ["automatización", "automatizacion", "python", "etl", "sql"],
    }

    if any(token in offer_lower for token in tokens["data"]):
        summary = (
            "Ingeniero eléctrico con enfoque en análisis de datos, automatización, visualización y modelado predictivo. "
            "Cuenta con experiencia en Python, Power BI, SQL, ETL y análisis exploratorio para convertir datos complejos en información útil para la toma de decisiones. "
            "Su perfil combina ingeniería, análisis de información y eficiencia operativa, con especial interés en soluciones basadas en datos y optimización de procesos."
        )
    elif any(token in offer_lower for token in tokens["bi"]):
        summary = (
            "Ingeniero eléctrico y analista de datos con experiencia en BI, ETL, Power BI, SQL, automatización y visualización de indicadores. "
            "Aplica análisis exploratorio, KPIs y transformación de datos para optimizar decisiones operativas y energéticas."
        )
    elif any(token in offer_lower for token in tokens["energia"]):
        summary = (
            "Ingeniero eléctrico con experiencia en análisis energético, eficiencia y optimización de procesos. "
            "Ha trabajado en automatización, gestión energética, indicadores operativos y soluciones de análisis para infraestructura y movilidad eléctrica."
        )
    elif any(token in offer_lower for token in tokens["ingenieria"]):
        summary = (
            "Ingeniero eléctrico con experiencia en infraestructura, automatización, mantenimiento, coordinación técnica y gestión de proyectos. "
            "Cuenta con desempeño en sistemas eléctricos, indicadores operativos, proyectos energéticos y optimización de procesos."
        )
    elif any(token in offer_lower for token in tokens["automatizacion"]):
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

    final_keywords = gemini_keywords + matched_keywords + [item for item in ordered_keywords if item not in matched_keywords]

    return {
        "summary": summary,
        "keywords": final_keywords[:20],
        "experiencia": ordered_experience[:4],
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

    html = build_cv_html(
        {
            "perfil_profesional": {"resumen": adapted["summary"]},
            "habilidades": adapted["keywords"],
            "experiencia": adapted["experiencia"],
            "formacion": profile.get("formacion", []),
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
            print(json.dumps({"pdf": item["pdf"], "cargo": item["analysis"].get("cargo_detectado")}, ensure_ascii=False, indent=2))
