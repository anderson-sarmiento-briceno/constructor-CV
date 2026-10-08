from docx import Document

from src.engine import adapt_profile_to_offer, adapt_content_with_llm, generate_all_cv_for_offers
from src.rendering.pdf_renderer import render_cv_to_pdf


def llm_result(experiences, origin="fallback_local", herramientas=None):
    """Respuesta simulada de adapt_experiences_and_skills (sin llamar a la API)."""
    herramientas = herramientas or []
    return {
        "descripciones": [experience.get("descripcion", "") for experience in experiences],
        "diagnosticos": [
            {"llm_consultado": True, "llm_respondio": origin == "llm", "origen": origin,
             "motivo_fallback": [] if origin == "llm" else ["respuesta vacía"], "texto_propuesto": ""}
            for _ in experiences
        ],
        "habilidades": {"aptitudes_clave": [], "herramientas": herramientas, "nuevas_tecnologias": [], "competencias": []},
        "diagnostico_habilidades": {
            "llm_consultado": True, "llm_respondio": bool(herramientas),
            "elementos_habilidad_propuestos": len(herramientas),
        },
    }


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


def test_generate_all_cv_for_offers_processes_batch(tmp_path, monkeypatch):
    # Sin red: el modelo "no responde" y todo el flujo usa los respaldos locales.
    monkeypatch.setattr("src.llm.llm.chat", lambda *args, **kwargs: {})
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
    # Sin resumen válido del modelo se usa el resumen escrito en el perfil maestro.
    assert adapted["summary"] == "Ingeniero eléctrico"
    assert adapted["summary_origin"] == "fallback_local"


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
    monkeypatch.setattr(engine, "adapt_experiences_and_skills", lambda profile, experiences, *args: llm_result(experiences))
    adapted = {"experiencia": [], "keywords": [], "logros": []}

    result = adapt_content_with_llm(profile, "Visualización de información con Tableau", adapted)

    assert result["software"] == ["Tableau", "Python", "AWS"]
    assert result["nuevas_tecnologias"] == ["Cloud", "Claude"]  # AWS ya está en SOFTWARE
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
    monkeypatch.setattr(engine, "adapt_experiences_and_skills", lambda profile, experiences, *args: llm_result(experiences))
    adapted = {"experiencia": [], "keywords": [], "logros": []}

    result = adapt_content_with_llm(
        profile,
        "Buscamos experiencia en Tableau, AWS y análisis predictivo.",
        adapted,
    )

    assert len(result["aptitudes"]) == 5
    assert result["aptitudes"][0] == "Análisis predictivo"
    assert len(result["software"]) == 8
    assert result["software"][:2] == ["Tableau", "AWS"]
    assert "AWS" not in result["nuevas_tecnologias"]  # ya está en SOFTWARE: no se repite
    assert len(result["nuevas_tecnologias"]) == 5
    assert len(result["competencias"]) == 6
    assert result["competencias"][0] == "Análisis predictivo"


def test_master_summary_fallback_is_shortened_by_whole_sentences():
    from src.engine import shorten_by_sentences

    long_text = " ".join(f"Oración número {index} con varias palabras de relleno para el perfil." for index in range(30))
    short = shorten_by_sentences(long_text, max_words=40)

    assert len(short.split()) <= 40
    assert short.endswith(".")


def test_logros_are_related_to_offer_and_never_padded_with_unrelated_or_repeated(monkeypatch):
    import src.engine as engine

    profile = {
        "aptitudes": [], "software": ["Python"], "nuevas_tecnologias": [], "competencias": [], "habilidades": [],
        "certificaciones": [],
        "logros": [
            "Modelo de churn en Python con 30 % de mejora.",
            "Dashboard de ventas en Tableau.",
            "Bot de agendamiento de citas médicas.",
            "Reducción del 40% en accidentes de obra.",
            "Curso de oratoria.",
        ],
    }
    experiences = [{"empresa": "X", "cargo": "Y", "descripcion": "Reduje en 40% los accidentes de obra."}]
    monkeypatch.setattr(engine, "adapt_experiences_and_skills", lambda profile, experiences, *args: llm_result(experiences))
    adapted = {"experiencia": experiences, "keywords": [], "logros": []}

    result = adapt_content_with_llm(profile, "Buscamos experto en Python para modelos de churn", adapted)

    assert result["logros"][0] == "Modelo de churn en Python con 30% de mejora."
    assert "Reducción del 40% en accidentes de obra." not in result["logros"]  # repite la experiencia
    assert "Curso de oratoria." not in result["logros"]  # sin relación con la oferta
    assert len(result["logros"]) == 2  # 1 relacionado + mínimo de 2 con uno que no repite


def test_sidebar_prefers_tools_mentioned_in_cv_and_skips_near_duplicates(monkeypatch):
    import src.engine as engine

    profile = {
        "aptitudes": [], "nuevas_tecnologias": [], "habilidades": [], "certificaciones": [],
        "software": ["Python", "MetaTrader 5", "Power BI", "Visualización Power BI", "Excel", "AutoCAD",
                     "SAP", "Trello", "Jira", "Tableau"],
        "competencias": [],
    }
    monkeypatch.setattr(engine, "adapt_experiences_and_skills", lambda profile, experiences, *args: llm_result(experiences))
    adapted = {"summary": "Soy analista y uso Tableau a diario.", "experiencia": [], "keywords": [], "logros": []}

    result = adapt_content_with_llm(profile, "Buscamos analista con Python y Power BI", adapted)

    assert result["software"][:3] == ["Python", "Power BI", "Tableau"]  # oferta, luego lo que el CV menciona
    assert "Visualización Power BI" not in result["software"]  # casi duplicado de "Power BI"


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

    monkeypatch.setattr(
        engine, "adapt_experiences_and_skills",
        lambda profile, experiences, *args: llm_result(experiences, origin="llm", herramientas=["Tableau"]),
    )
    adapted = {
        "summary": "Tableau para visualización de datos",
        "summary_origin": "fallback_local",
        "summary_match": {"porcentaje": 50, "coincidencias": 1, "prioridades_evaluadas": 2},
        "analysis": {"resumen_intentos": [{"llm_respondio": True, "valido": False, "motivos_rechazo": ["breve"]}]},
        "analysis_priorities": ["Tableau", "Python avanzado"],
        "experiencia": [{"empresa": "Enel", "cargo": "Ingeniero", "descripcion": "Análisis de datos con Tableau."}],
        "keywords": [],
        "logros": [],
    }

    result = adapt_content_with_llm(profile, "Tableau Python avanzado", adapted)
    report = result["reporte_adaptacion"]

    assert report["perfil"]["origen"] == "fallback_local"
    assert report["perfil"]["uso_llm_pct"] == 0
    assert report["perfil"]["intentos"] == 1
    assert report["perfil"]["causa_fallback"] == "breve"
    assert report["experiencias"][0]["origen"] == "llm"
    assert report["experiencias"][0]["uso_llm_pct"] == 100
    assert report["experiencias"][0]["final_match"] == "1/2 (50%)"
    assert report["habilidades"]["habilidades_coincidentes"] == 1
    assert report["habilidades"]["uso_llm_pct"] == 100
    assert report["totales"]["porcentaje_bloques_llm_aceptados"] == 50
    assert "coincidencia_final" not in report["experiencias"][0]
    assert len(report["habilidades"]) == 5


def test_logros_skip_a_project_already_told_in_the_experiences():
    from src.engine import select_logros_for_cv

    profile = {"logros": [
        "Modelos de análisis predictivo para apuestas deportivas con Python, mejorando un 25% la tasa de aciertos.",
        "Informes automatizados de consumo energético con telemetría, reduciendo un 80% el tiempo de generación.",
        "Dashboards de consumo energético en Power BI para la operación de la flota.",
        "Alertas tempranas de armónicos con Python y AWS, reduciendo un 55% el tiempo de detección.",
        "Atención de fallas críticas con Tableau, disminuyendo un 35% el tiempo de respuesta.",
    ]}
    experiences = [{"descripcion": "Construí modelos de clasificación para apuestas deportivas con Python."}]

    selected = select_logros_for_cv(profile, "Python, Power BI, Tableau, análisis predictivo", experiences)

    assert not any("apuestas" in logro for logro in selected[:4])
    assert any("Informes automatizados" in logro for logro in selected)


def test_skills_only_enter_their_own_category_and_offer_acronyms_are_not_companies(monkeypatch):
    import src.engine as engine
    import src.llm.llm as llm

    profile = {"aptitudes": ["Inteligencia Artificial", "Análisis predictivo"], "software": ["R", "Python"],
               "nuevas_tecnologias": ["Make"], "competencias": [], "habilidades": [], "certificaciones": []}
    result = llm_result([])
    result["habilidades"]["aptitudes_clave"] = ["R", "Make", "Inteligencia Artificial"]
    monkeypatch.setattr(engine, "adapt_experiences_and_skills", lambda *args: result)

    adapted = adapt_content_with_llm(profile, "Inteligencia Artificial con R y Make", {"experiencia": [], "keywords": [], "logros": []})

    assert "R" not in adapted["aptitudes"] and "Make" not in adapted["aptitudes"]
    # La organización se busca por palabra completa: "Media" no está dentro de "intermedia".
    experience = {"descripcion": "Construí reportes de consumo con Python para la operación intermedia de la flota."}
    text = ("Construí reportes de consumo con Python para la operación intermedia de la flota, "
            "consolidando datos de telemetría en tableros de seguimiento para la operación diaria.")
    assert not any("organización" in issue for issue in llm._experience_issues(text, experience, "", ["Media"]))
    assert any("organización" in issue
               for issue in llm._experience_issues(text + " Trabajé para Media.", experience, "", ["Media"]))
