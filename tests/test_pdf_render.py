from docx import Document

from src.engine import adapt_profile_to_offer, adapt_content_with_ollama, generate_all_cv_for_offers
from src.rendering.pdf_renderer import render_cv_to_pdf


def test_render_cv_to_pdf_creates_file(tmp_path):
    output = tmp_path / "cv_test.pdf"
    html = "<html><body><h1>CV prueba</h1><p>Texto</p></body></html>"

    path = render_cv_to_pdf(html, str(output))

    assert path == str(output)
    assert output.exists()
    assert output.stat().st_size > 0


def test_render_cv_to_pdf_accepts_structured_profile(tmp_path):
    output = tmp_path / "cv_structured.pdf"
    profile = {
        "datos_personales": {
            "nombre": "Anderson Sarmiento",
            "profesion": "Ingeniero Eléctrico",
            "correo": "anderson@email.com",
            "telefono": "+57 300 000 0000",
            "linkedin": "linkedin.com/in/anderson",
        },
        "perfil_profesional": {
            "resumen": "Ingeniero eléctrico con experiencia en automatización, análisis de datos y eficiencia energética."
        },
        "habilidades": ["Python", "Power BI", "SQL", "ETL", "Machine Learning"],
        "experiencia": [
            {"empresa": "Green Mobil", "cargo": "Científico de Datos", "descripcion": "Modelos predictivos y ETL."},
            {"empresa": "Enel Colombia", "cargo": "Ingeniero", "descripcion": "Automatización y análisis eléctrico."},
        ],
        "formacion": [
            {"titulo": "Ingeniería Eléctrica", "institucion": "Universidad Distrital", "anio": 2013}
        ],
    }

    path = render_cv_to_pdf(profile, str(output))

    assert path == str(output)
    assert output.exists()
    assert output.stat().st_size > 0


def test_generate_all_cv_for_offers_processes_batch(tmp_path):
    offers_dir = tmp_path / "ofertas"
    offers_dir.mkdir()
    profiles_dir = tmp_path / "config"
    profiles_dir.mkdir()

    doc = Document()
    doc.add_paragraph("Buscamos Data Scientist con Python, Power BI, SQL y ETL")
    doc.save(str(offers_dir / "Oferta_1.docx"))

    doc2 = Document()
    doc2.add_paragraph("Necesitamos BI con Power BI, SQL y dashboards")
    doc2.save(str(offers_dir / "Oferta_2.docx"))

    profile_path = profiles_dir / "perfil_maestro.json"
    profile_path.write_text(
        '{"datos_personales":{"nombre":"Anderson Sarmiento","profesion":"Ingeniero Eléctrico"},'
        '"perfil_profesional":{"resumen":"Ingeniero eléctrico con análisis de datos"},'
        '"habilidades":["Python","Power BI","SQL","ETL","Machine Learning","Automatización"],'
        '"experiencia":[{"empresa":"Green Mobil","cargo":"Científico de Datos","descripcion":"ETL y modelos predictivos"},{"empresa":"Enel Colombia","cargo":"Ingeniero","descripcion":"Automatización y mantenimiento"}],'
        '"formacion":[]}',
        encoding="utf-8",
    )

    results = generate_all_cv_for_offers(str(offers_dir), str(profiles_dir / "perfil_maestro.json"), str(tmp_path / "output"))

    assert len(results) == 2
    assert all("pdf" in item for item in results)
    assert any("Oferta_1" in item["pdf"] for item in results)
    assert any("Oferta_2" in item["pdf"] for item in results)


def test_adapt_profile_to_offer_prioritizes_relevant_experience():
    profile = {
        "perfil_profesional": {"resumen": "Ingeniero eléctrico"},
        "habilidades": ["Python", "Power BI", "SQL", "ETL", "Machine Learning", "ISO 50001", "Movilidad eléctrica"],
        "experiencia": [
            {"empresa": "Enel Colombia", "cargo": "Ingeniero", "fechas": "Jul 2010 – Ago 2023", "descripcion": "Mantenimiento eléctrico y gestión"},
            {"empresa": "Green Mobil", "cargo": "Científico de Datos", "fechas": "Jul 2025 – Sep 2025", "descripcion": "Modelos predictivos, ETL, Python, Power BI, ISO 50001 y movilidad eléctrica"},
        ],
        "formacion": [],
    }

    offer_text = "Buscamos Data Scientist con Python, Power BI, SQL, ETL, Machine Learning, ISO 50001 y movilidad eléctrica"
    adapted = adapt_profile_to_offer(profile, offer_text)

    assert adapted["keywords"][0] == "Python"
    assert adapted["experiencia"][0]["empresa"] == "Green Mobil"
    assert "ISO 50001" in adapted["keywords"]


def test_adapt_profile_to_offer_is_dynamic_for_any_offer():
    profile = {
        "perfil_profesional": {"resumen": "Ingeniero eléctrico"},
        "habilidades": ["Python", "Power BI", "SQL", "ETL", "Machine Learning", "Automatización", "Eficiencia energética"],
        "experiencia": [
            {"empresa": "Enel Colombia", "cargo": "Ingeniero", "descripcion": "Automatización y mantenimiento eléctrico"},
            {"empresa": "Green Mobil", "cargo": "Científico de Datos", "descripcion": "Modelos de consumo y BI"},
        ],
        "formacion": [],
    }

    offer_text = "Necesitamos un analista BI senior con Power BI, SQL, automatización, ETL y dashboards ejecutivos"
    adapted = adapt_profile_to_offer(profile, offer_text)

    assert "Power BI" in adapted["keywords"]
    assert "SQL" in adapted["keywords"]
    assert adapted["summary"]
    assert "BI" in adapted["summary"].upper() or "ANALISTA" in adapted["summary"].upper()


def test_adapted_keywords_differ_between_distinct_offers():
    profile = {
        "datos_personales": {"profesion": "Ingeniero Eléctrico"},
        "perfil_profesional": {"resumen": "Ingeniero con experiencia en análisis de datos."},
        "habilidades": [
            "Visualización Power BI", "Tableau", "Automatización de reportes",
            "Movilidad eléctrica", "Gestión energética", "Análisis de consumo energético",
            "Datos de telemetría", "Modelos predictivos",
        ],
        "experiencia": [
            {"empresa": "Enel", "cargo": "Profesional en Infraestructura y Redes", "fechas": "Jul 2010 – Ago 2023", "descripcion": "Dashboards HSEQ en Power BI y Tableau para indicadores de accidentabilidad."},
            {"empresa": "Green Movil", "cargo": "Científico de Datos", "fechas": "Jul 2025 – Sep 2025", "descripcion": "Análisis de telemetría, consumo energético y modelos predictivos de desgaste de flota."},
        ],
        "logros": [],
    }
    bi_offer = "Especialista BI para dashboards en Power BI y Tableau, visualización de datos y reportes."
    fleet_offer = "Científico de datos para movilidad eléctrica, telemetría, consumo energético y modelos predictivos."

    bi = adapt_profile_to_offer(profile, bi_offer)
    fleet = adapt_profile_to_offer(profile, fleet_offer)

    assert "Visualización Power BI" in bi["keywords"]
    assert "Datos de telemetría" in fleet["keywords"]
    assert bi["keywords"] != fleet["keywords"]
    assert bi["summary"] != fleet["summary"]
    assert bi["experiencia"][0]["empresa"] == "Green Movil"
    assert fleet["experiencia"][0]["empresa"] == "Green Movil"
    assert bi["experiencia"][-1]["empresa"] == "Enel"


def test_adapt_content_does_not_fill_unrelated_technologies(monkeypatch):
    import src.engine as engine

    profile = {
        "aptitudes": [],
        "software": ["Python", "Tableau", "AWS"],
        "nuevas_tecnologias": ["Cloud", "AWS", "Claude"],
        "competencias": [],
        "habilidades": ["Python", "Tableau", "AWS"],
        "certificaciones": [],
    }
    def experience_fallback(experience, *args, diagnostics=None, **kwargs):
        if diagnostics is not None:
            diagnostics.update({"ollama_consultado": True, "ollama_respondio": False, "origen": "fallback_local", "motivo_fallback": ["respuesta vacía"]})
        return experience.get("descripcion", "")

    def empty_skill_result(*args, diagnostics=None, **kwargs):
        if diagnostics is not None:
            diagnostics.update({"ollama_consultado": True, "ollama_respondio": False, "elementos_habilidad_propuestos": 0})
        return {"aptitudes_clave": [], "herramientas": [], "nuevas_tecnologias": [], "competencias": [], "logros": []}

    monkeypatch.setattr(engine, "adapt_experience_to_offer", experience_fallback)
    monkeypatch.setattr(engine, "adapt_skills_to_offer", empty_skill_result)
    adapted = {"experiencia": [], "keywords": [], "logros": []}

    result = adapt_content_with_ollama(profile, "Visualización de información con Tableau", adapted)

    assert result["software"] == ["Tableau", "Python", "AWS"]
    assert result["nuevas_tecnologias"] == ["Cloud", "AWS", "Claude"]
    assert result["keywords"] == ["Tableau"]


def test_sidebar_skill_groups_prioritize_offer_matches_then_fill_to_five(monkeypatch):
    import src.engine as engine

    profile = {
        "aptitudes": ["Análisis predictivo", "Gestión energética", "Liderazgo", "Gestión de proyectos", "Análisis de datos", "HSEQ"],
        "software": ["Python", "Tableau", "Power BI", "PostgreSQL", "AWS", "Excel", "Spark", "SAP", "AutoCAD", "PSS/E"],
        "nuevas_tecnologias": ["Cloud", "AWS", "GitHub Copilot", "Claude", "Hugging Face", "Agentes de IA"],
        "competencias": ["Análisis predictivo", "ETL", "Machine Learning", "Visualización de datos", "Modelos de regresión", "Ingeniería de Datos", "Redes eléctricas"],
        "habilidades": [],
        "certificaciones": [],
    }
    monkeypatch.setattr(engine, "adapt_experience_to_offer", lambda experience, *args, **kwargs: experience.get("descripcion", ""))
    monkeypatch.setattr(engine, "adapt_skills_to_offer", lambda *args, **kwargs: {
        "aptitudes_clave": [], "herramientas": [], "nuevas_tecnologias": [],
        "competencias": [], "logros": [],
    })
    adapted = {"experiencia": [], "keywords": [], "logros": []}

    result = adapt_content_with_ollama(
        profile,
        "Buscamos experiencia en Tableau, AWS y análisis predictivo.",
        adapted,
    )

    assert len(result["aptitudes"]) == 5
    assert result["aptitudes"][0] == "Análisis predictivo"
    assert len(result["software"]) == 8
    assert result["software"][:2] == ["Tableau", "AWS"]
    assert len(result["nuevas_tecnologias"]) == 5
    assert result["nuevas_tecnologias"][0] == "AWS"
    assert len(result["competencias"]) == 6
    assert result["competencias"][0] == "Análisis predictivo"


def test_adaptation_report_tracks_sources_and_priority_percentages(monkeypatch):
    import src.engine as engine

    profile = {
        "aptitudes": [],
        "software": ["Tableau"],
        "nuevas_tecnologias": [],
        "competencias": ["Visualización de datos"],
        "habilidades": ["Tableau", "Visualización de datos"],
        "certificaciones": [],
    }

    def accepted_experience(experience, *args, diagnostics=None, **kwargs):
        if diagnostics is not None:
            diagnostics.update({"ollama_consultado": True, "ollama_respondio": True, "origen": "ollama", "motivo_fallback": []})
        return experience["descripcion"]

    def skill_result(*args, diagnostics=None, **kwargs):
        if diagnostics is not None:
            diagnostics.update({"ollama_consultado": True, "ollama_respondio": True, "elementos_habilidad_propuestos": 1})
        return {"aptitudes_clave": [], "herramientas": ["Tableau"], "nuevas_tecnologias": [], "competencias": [], "logros": []}

    monkeypatch.setattr(engine, "adapt_experience_to_offer", accepted_experience)
    monkeypatch.setattr(engine, "adapt_skills_to_offer", skill_result)
    adapted = {
        "summary": "Tableau para visualización de datos",
        "summary_origin": "fallback_local",
        "summary_match": {"porcentaje": 50, "coincidencias": 1, "prioridades_evaluadas": 2},
        "analysis": {"resumen_intentos": [{"ollama_respondio": True, "valido": False, "motivos_rechazo": ["breve"]}]},
        "analysis_priorities": ["Tableau", "Python avanzado"],
        "experiencia": [{"empresa": "Enel", "cargo": "Ingeniero", "descripcion": "Análisis de datos con Tableau."}],
        "keywords": [],
        "logros": [],
    }

    result = adapt_content_with_ollama(profile, "Tableau Python avanzado", adapted)
    report = result["reporte_adaptacion"]

    assert report["perfil"]["origen"] == "fallback_local"
    assert report["perfil"]["uso_ollama_pct"] == 0
    assert report["perfil"]["intentos"] == 1
    assert report["perfil"]["causa_fallback"] == "breve"
    assert report["experiencias"][0]["origen"] == "ollama"
    assert report["experiencias"][0]["uso_ollama_pct"] == 100
    assert report["experiencias"][0]["final_match"] == "1/2 (50%)"
    assert report["habilidades"]["habilidades_coincidentes"] == 1
    assert report["habilidades"]["uso_ollama_pct"] == 100
    assert report["totales"]["porcentaje_bloques_ollama_aceptados"] == 50
    assert "coincidencia_final" not in report["experiencias"][0]
    assert len(report["habilidades"]) == 5
