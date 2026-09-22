import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, TA_JUSTIFY, getSampleStyleSheet
from reportlab.platypus import BaseDocTemplate, Frame, HRFlowable, Image, PageTemplate, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


def _normalize_profile(profile):
    if not isinstance(profile, dict):
        return {}

    if "datos_personales" in profile:
        return profile

    return {
        "datos_personales": {
            "nombre": profile.get("nombre", "Anderson Sarmiento"),
            "profesion": profile.get("profesion", "Ingeniero Eléctrico"),
            "correo": profile.get("correo", ""),
            "telefono": profile.get("telefono", ""),
            "linkedin": profile.get("linkedin", ""),
            "ciudad": profile.get("ciudad", "Bogotá, Colombia"),
        },
        "perfil_profesional": {"resumen": profile.get("resumen", "")},
        "habilidades": profile.get("habilidades", []),
        "experiencia": profile.get("experiencia", []),
        "formacion": profile.get("formacion", []),
    }


def _extract_text_from_markup(markup):
    if not markup:
        return "CV generado"

    if isinstance(markup, dict):
        markup = "CV generado"

    text = str(markup)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n+", "\n", text)
    text = text.replace("\xa0", " ")
    return text.strip()


def _safe_text(value, default=""):
    return value if isinstance(value, str) and value.strip() else default


def _contact_line(profile):
    dp = profile.get("datos_personales", {})
    parts = []
    phone = _safe_text(dp.get("telefono"))
    email = _safe_text(dp.get("correo"))
    linkedin = _safe_text(dp.get("linkedin"))
    city = _safe_text(dp.get("ciudad"), "Bogotá, Colombia")
    if phone:
        parts.append(phone)
    if email:
        parts.append(email)
    if linkedin:
        parts.append(linkedin)
    if city:
        parts.append(city)
    return " | ".join(parts) if parts else city


def _experience_block(exp):
    empresa = _safe_text(exp.get("empresa"), "Empresa")
    cargo = _safe_text(exp.get("cargo"), "Cargo")
    descripcion = _safe_text(exp.get("descripcion"), "")
    fechas = _safe_text(exp.get("fechas"), "")
    return {
        "empresa": empresa,
        "cargo": cargo,
        "descripcion": descripcion,
        "fechas": fechas,
    }


def render_cv_to_pdf_legacy(profile_or_html, output_pdf_path):
    """Genera un CV profesional, ATS-friendly y completo para el perfil real del candidato."""
    output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = _normalize_profile(profile_or_html if isinstance(profile_or_html, dict) else {})
    if not profile:
        html_text = _extract_text_from_markup(profile_or_html)
        fallback = html_text[:1200]
        profile = {
            "datos_personales": {
                "nombre": "Anderson Sarmiento",
                "profesion": "Ingeniero Eléctrico",
                "correo": "andersarb@gmail.com",
                "telefono": "321 212 1013",
                "linkedin": "anderson-sarmiento-briceno",
                "ciudad": "Bogotá, Colombia",
            },
            "perfil_profesional": {"resumen": fallback or "Ingeniero eléctrico con experiencia en automatización, análisis de datos y eficiencia energética."},
            "habilidades": ["Python", "Power BI", "SQL", "ETL", "Machine Learning"],
            "experiencia": [],
            "formacion": [],
        }

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()
    story = []

    accent = colors.HexColor("#0F172A")
    text_dark = colors.HexColor("#111827")
    text_light = colors.HexColor("#F8FAFC")
    muted = colors.HexColor("#475569")

    name_style = ParagraphStyle(
        "NameStyle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=accent,
        spaceAfter=3,
    )
    role_style = ParagraphStyle(
        "RoleStyle",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=accent,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "MetaStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10,
        textColor=muted,
        spaceAfter=8,
    )
    section_header = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=text_light,
        backColor=accent,
        borderPadding=4,
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=text_dark,
        spaceAfter=5,
    )
    bold_style = ParagraphStyle(
        "BoldStyle",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=text_dark,
        spaceAfter=4,
    )

    dp = profile.get("datos_personales", {})
    full_name = _safe_text(dp.get("nombre"), "Anderson Sarmiento")
    profession = _safe_text(dp.get("profesion"), "Ingeniero Eléctrico")
    target_title = _safe_text(profile.get("titulo_objetivo"), profession)
    professions = dp.get("profesiones", [profession])
    professions = [str(item).strip() for item in professions if str(item).strip()]
    title_parts = [target_title] + [item for item in professions if item.casefold() != target_title.casefold()]
    city = _safe_text(dp.get("ciudad"), "Bogotá, Colombia")
    phone = _safe_text(dp.get("telefono"), "321 212 1013")
    email = _safe_text(dp.get("correo"), "andersarb@gmail.com")
    linkedin = _safe_text(dp.get("linkedin"), "anderson-sarmiento-briceno")
    github = _safe_text(dp.get("github"), "https://github.com/anderson-sarmiento-briceno")

    summary = _safe_text(
        profile.get("perfil_profesional", {}).get("resumen"),
        "Ingeniero eléctrico con experiencia en infraestructura, automatización, análisis de datos y eficiencia energética."
    )

    skills = profile.get("habilidades", [])
    if not skills:
        skills = [
            "Gestión de Proyectos",
            "Análisis de Datos / ML",
            "ETL & Python",
            "Chatbots & Automatización",
            "Visualización Power BI",
            "Seguridad & HSEQ",
            "Liderazgo de Equipos",
        ]

    languages = profile.get("idiomas", [])
    if not languages:
        languages = ["Español — Nativo", "English — Intermedio"]

    courses = profile.get("cursos", [])
    if not courses:
        courses = [
            "Python Intermedio — Platzi — 2023",
            "BI con Power BI — Platzi — 2022",
            "Fundamentos de Bases de Datos — SENA",
        ]

    interests = profile.get("intereses", [])
    if not interests:
        interests = ["Deporte y actividad física", "Lectura técnica", "Música"]

    training = profile.get("formacion", [])
    if not training:
        training = [
            {"titulo": "Ingeniero Eléctrico", "institucion": "Universidad Distrital FJC", "anio": 2013},
            {"titulo": "Esp. Gerencia de Proyectos", "institucion": "Universidad del Bosque", "anio": 2015},
            {"titulo": "Científico de Datos", "institucion": "Platzi", "anio": "En curso"},
        ]

    experiences = profile.get("experiencia", [])
    if not experiences:
        experiences = [
            {"empresa": "Green Mobil", "cargo": "Científico de Datos", "fechas": "20 Jul 2025 – 15 Sep 2025", "descripcion": "Modelos predictivos, ETL y dashboards en Power BI."},
            {"empresa": "Consultor Freelance", "cargo": "Científico de Datos & Automatización", "fechas": "Sep 2023 – Jul 2025", "descripcion": "Chatbots, modelos ML y automatización de procesos."},
            {"empresa": "Enel", "cargo": "Profesional en Infraestructura y Redes", "fechas": "Jul 2010 – Ago 2023", "descripcion": "Gestión de proyectos MT/BT, análisis de redes y mantenimiento eléctrico."},
        ]

    logros = profile.get("logros", [
        "Modelo de regresión lineal de consumo energético orientado a ISO 50001.",
        "Pipelines ETL automatizados con Python para APIs, Excel y Siesa hacia PostgreSQL + Power BI.",
        "Chatbots de ventas con ManyChat + WhatsApp API: +35 % conversión y reducción de costos.",
    ])

    story.append(Paragraph(full_name, name_style))
    story.append(Paragraph(f"{profession} | {city}", role_style))
    story.append(Paragraph(f"{phone} | {email} | {linkedin}", meta_style))

    story.append(Paragraph("PERFIL PROFESIONAL", section_header))
    story.append(Paragraph(summary, body_style))

    story.append(Paragraph("CONTACTO", section_header))
    story.append(Paragraph(f"TEL: {phone}", body_style))
    story.append(Paragraph(f"EMAIL: {email}", body_style))
    story.append(Paragraph(f"LINKEDIN: {linkedin}", body_style))
    story.append(Paragraph(f"CIUDAD: {city}", body_style))

    story.append(Paragraph("APTITUDES CLAVE", section_header))
    story.append(Paragraph(" • ".join(str(skill) for skill in skills[:12]), body_style))

    story.append(Paragraph("EXPERIENCIA PROFESIONAL", section_header))
    for exp in experiences[:4]:
        item = _experience_block(exp)
        story.append(Paragraph(f"{item['empresa']} — {item['cargo']}", bold_style))
        if item["fechas"]:
            story.append(Paragraph(item["fechas"], meta_style))
        if item["descripcion"]:
            story.append(Paragraph(item["descripcion"], body_style))
        story.append(Spacer(1, 4))

    story.append(Paragraph("EDUCACIÓN", section_header))
    for item in training[:5]:
        titulo = _safe_text(item.get("titulo"), "")
        institucion = _safe_text(item.get("institucion"), "")
        anio = item.get("anio")
        label = f"{titulo} - {institucion}"
        if anio:
            label += f" - {anio}"
        story.append(Paragraph(label, body_style))

    if courses:
        story.append(Paragraph("FORMACIÓN COMPLEMENTARIA", section_header))
        for curso in courses[:5]:
            story.append(Paragraph(f"• {curso}", body_style))

    if languages:
        story.append(Paragraph("IDIOMAS", section_header))
        for idioma in languages[:6]:
            story.append(Paragraph(f"• {idioma}", body_style))

    story.append(Paragraph("COMPETENCIAS TÉCNICAS", section_header))
    for skill in skills[:12]:
        story.append(Paragraph(f"• {skill}", body_style))

    story.append(Paragraph("LOGROS DESTACADOS", section_header))
    for logro in logros[:5]:
        story.append(Paragraph(f"• {logro}", body_style))

    if interests:
        story.append(Paragraph("INTERESES", section_header))
        for item in interests[:6]:
            story.append(Paragraph(f"• {item}", body_style))

    doc.build(story)
    return str(output_path)


def render_cv_to_pdf_model_legacy(profile_or_html, output_pdf_path):
    """Renderiza el CV con la composición del modelo: sidebar izquierdo y contenido ATS a la derecha."""
    output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = _normalize_profile(profile_or_html if isinstance(profile_or_html, dict) else {})

    if not profile:
        profile = _normalize_profile({})

    dp = profile.get("datos_personales", {})
    full_name = _safe_text(dp.get("nombre"), "Anderson Sarmiento")
    profession = _safe_text(dp.get("profesion"), "Ingeniero Eléctrico")
    target_title = _safe_text(profile.get("titulo_objetivo"), profession)
    professions = dp.get("profesiones", [profession])
    professions = [str(item).strip() for item in professions if str(item).strip()]
    title_parts = [target_title] + [item for item in professions if item.casefold() != target_title.casefold()]
    phone = _safe_text(dp.get("telefono"), "321 212 1013")
    email = _safe_text(dp.get("correo"), "andersarb@gmail.com")
    linkedin = _safe_text(dp.get("linkedin"), "anderson-sarmiento-briceno")
    github = _safe_text(dp.get("github"), "https://github.com/anderson-sarmiento-briceno")
    city = _safe_text(dp.get("ciudad"), "Bogotá, Colombia")
    summary = _safe_text(
        profile.get("perfil_profesional", {}).get("resumen"),
        "Ingeniero eléctrico con experiencia en infraestructura, automatización, análisis de datos y eficiencia energética.",
    )

    skills = profile.get("habilidades", []) or ["Gestión de Proyectos", "Python", "Power BI", "SQL", "ETL", "Machine Learning"]
    languages = profile.get("idiomas", []) or ["Español - Nativo", "English - Intermedio"]
    training = profile.get("formacion", [])
    courses = profile.get("cursos", [])
    experiences = profile.get("experiencia", [])
    logros = profile.get("logros", [])
    interests = profile.get("intereses", [])

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#173F4F")
    teal = colors.HexColor("#2E6572")
    dark = colors.HexColor("#1F2933")
    gray = colors.HexColor("#5F6B72")
    white = colors.white

    sidebar_heading = ParagraphStyle(
        "ModelSidebarHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=9, leading=11, textColor=white, spaceBefore=9, spaceAfter=5,
    )
    sidebar_text = ParagraphStyle(
        "ModelSidebarText", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8, leading=10.5, textColor=white, spaceAfter=4,
    )
    name_style = ParagraphStyle(
        "ModelName", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=24, leading=27, textColor=navy, spaceAfter=2,
    )
    title_style = ParagraphStyle(
        "ModelTitle", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=10, leading=12, textColor=teal, spaceAfter=3,
    )
    contact_style = ParagraphStyle(
        "ModelContact", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8, leading=10, textColor=gray, spaceAfter=7,
    )
    section_style = ParagraphStyle(
        "ModelSection", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=10, leading=12, textColor=navy, spaceBefore=8, spaceAfter=5,
        borderWidth=0, borderPadding=0,
    )
    body_style = ParagraphStyle(
        "ModelBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.7, leading=11.3, textColor=dark, spaceAfter=4,
    )
    job_style = ParagraphStyle(
        "ModelJob", parent=body_style, fontName="Helvetica-Bold", textColor=navy, spaceAfter=2,
    )
    date_style = ParagraphStyle(
        "ModelDate", parent=body_style, fontSize=8, leading=9.5, textColor=gray, spaceAfter=3,
    )

    def bullet_list(items, style):
        return [Paragraph(f"- {item}", style) for item in items if str(item).strip()]

    sidebar = []
    photo_value = _safe_text(dp.get("foto"), "")
    photo_path = Path(photo_value) if photo_value else Path(__file__).resolve().parents[2] / "foto.jpeg"
    if photo_path.exists():
        photo = Image(str(photo_path), width=112, height=112)
        photo.hAlign = "CENTER"
        sidebar.extend([photo, Spacer(1, 8)])
    sidebar.append(Paragraph("CONTACTO", sidebar_heading))
    sidebar.extend([
        Paragraph(phone, sidebar_text),
        Paragraph(email, sidebar_text),
        Paragraph(linkedin, sidebar_text),
        Paragraph(city, sidebar_text),
    ])
    sidebar.append(Paragraph("EDUCACIÓN", sidebar_heading))
    for item in training:
        title = _safe_text(item.get("titulo"), "Formación")
        institution = _safe_text(item.get("institucion"), "")
        year = str(item.get("anio", ""))
        sidebar.append(Paragraph(title, sidebar_text))
        if institution:
            sidebar.append(Paragraph(institution, sidebar_text))
        if year:
            sidebar.append(Paragraph(year, sidebar_text))
    sidebar.append(Paragraph("IDIOMAS", sidebar_heading))
    sidebar.extend(bullet_list(languages, sidebar_text))
    if interests:
        sidebar.append(Paragraph("INTERESES", sidebar_heading))
        sidebar.extend(bullet_list(interests, sidebar_text))

    main_rows = [[
        Paragraph(full_name, name_style),
        Paragraph(profession, title_style),
        Paragraph(f"{phone} | {email} | {linkedin} | {city}", contact_style),
        Paragraph("PERFIL PROFESIONAL", section_style),
        Paragraph(summary, body_style),
    ]]
    main_rows.append([[Paragraph("EXPERIENCIA PROFESIONAL", section_style)]])
    for experience in experiences:
        item = _experience_block(experience)
        job_content = [Paragraph(f"{item['empresa']} | {item['cargo']}", job_style)]
        if item["fechas"]:
            job_content.append(Paragraph(item["fechas"], date_style))
        job_content.append(Paragraph(item["descripcion"], body_style))
        main_rows.append([job_content])

    main_rows.append([[Paragraph("COMPETENCIAS TÉCNICAS", section_style)]])
    for item in bullet_list(skills, body_style):
        main_rows.append([[item]])
    if courses:
        main_rows.append([[Paragraph("FORMACIÓN COMPLEMENTARIA", section_style)]])
        for item in bullet_list(courses, body_style):
            main_rows.append([[item]])
    if logros:
        main_rows.append([[Paragraph("LOGROS DESTACADOS", section_style)]])
        for item in bullet_list(logros, body_style):
            main_rows.append([[item]])

    table_data = [[sidebar if index == 0 else "", row[0]] for index, row in enumerate(main_rows)]
    table = Table(table_data, colWidths=[158, 382], repeatRows=0)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 14),
        ("RIGHTPADDING", (0, 0), (0, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (1, 0), (1, -1), 18),
        ("RIGHTPADDING", (1, 0), (1, -1), 4),
        ("BACKGROUND", (0, 0), (0, -1), navy),
        ("BACKGROUND", (1, 0), (1, -1), colors.white),
    ]))

    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=28, rightMargin=28, topMargin=24, bottomMargin=24)
    doc.build([table])
    return str(output_path)


def render_cv_to_pdf_model(profile_or_html, output_pdf_path):
    """Renderiza una plantilla carta de dos columnas inspirada directamente en el CV modelo."""
    output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = _normalize_profile(profile_or_html if isinstance(profile_or_html, dict) else {})
    dp = profile.get("datos_personales", {})

    full_name = _safe_text(dp.get("nombre"), "Anderson Sarmiento")
    profession = _safe_text(dp.get("profesion"), "Ingeniero Eléctrico")
    target_title = _safe_text(profile.get("titulo_objetivo"), profession)
    professions = dp.get("profesiones", [profession])
    professions = [str(item).strip() for item in professions if str(item).strip()]
    title_parts = [target_title] + [
        item for item in professions if item.casefold() != target_title.casefold()
    ]
    phone = _safe_text(dp.get("telefono"), "321 212 1013")
    email = _safe_text(dp.get("correo"), "andersarb@gmail.com")
    linkedin = _safe_text(dp.get("linkedin"), "anderson-sarmiento-briceno")
    github = _safe_text(dp.get("github"), "https://github.com/anderson-sarmiento-briceno")
    city = _safe_text(dp.get("ciudad"), "Bogotá, Colombia")
    summary = _safe_text(
        profile.get("perfil_profesional", {}).get("resumen"),
        "Ingeniero eléctrico con experiencia en infraestructura, automatización, análisis de datos y eficiencia energética.",
    )
    skills = profile.get("habilidades", []) or ["Gestión de Proyectos", "Python", "Power BI", "SQL", "ETL", "Machine Learning"]
    languages = profile.get("idiomas", []) or ["Español - Nativo", "English - Intermedio"]
    training = profile.get("formacion", []) or []
    courses = profile.get("cursos", []) or []
    experiences = profile.get("experiencia", []) or []
    logros = profile.get("logros", []) or []
    interests = profile.get("intereses", []) or []

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#173F4F")
    teal = colors.HexColor("#2E6572")
    dark = colors.HexColor("#1F2933")
    gray = colors.HexColor("#63727A")
    light_line = colors.HexColor("#B8C8CC")
    page_width, page_height = 612, 792
    left_x, left_width = 28, 166
    main_x, main_width = 218, 366
    top = 766
    bottom = 26

    sidebar_heading = ParagraphStyle(
        "ModelSidebarHeadingFinal", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=9, leading=11, textColor=colors.white, spaceBefore=8, spaceAfter=6,
    )
    sidebar_text = ParagraphStyle(
        "ModelSidebarTextFinal", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8, leading=9.7, textColor=colors.white, spaceAfter=5,
    )
    sidebar_name = ParagraphStyle(
        "ModelSidebarNameFinal", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=15, leading=16, textColor=colors.white, spaceAfter=2,
    )
    sidebar_role = ParagraphStyle(
        "ModelSidebarRoleFinal", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=7.8, leading=9, textColor=colors.white, spaceAfter=1,
    )
    name_style = ParagraphStyle(
        "ModelNameFinal", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=24, leading=25, textColor=navy, spaceAfter=2,
    )
    title_style = ParagraphStyle(
        "ModelTitleFinal", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=9.5, leading=11, textColor=teal, spaceAfter=3,
    )
    contact_style = ParagraphStyle(
        "ModelContactFinal", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=7.8, leading=9, textColor=gray, spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "ModelSectionFinal", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=9.5, leading=11, textColor=navy, spaceBefore=6, spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "ModelBodyFinal", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.3, leading=10.2, textColor=dark, spaceAfter=3, alignment=TA_JUSTIFY,
    )
    job_style = ParagraphStyle(
        "ModelJobFinal", parent=body_style, fontName="Helvetica-Bold", textColor=navy, spaceAfter=1,
    )
    date_style = ParagraphStyle(
        "ModelDateFinal", parent=body_style, fontSize=7.8, leading=8.8, textColor=gray, spaceAfter=2,
    )

    def para(value, style):
        return Paragraph(escape(str(value)), style)

    def bullet(value, style):
        return Paragraph(f'<font color="#2E6572">&#8226;</font> {escape(str(value))}', style)

    def sidebar_block(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(navy)
        canvas.rect(left_x, 0, left_width, page_height, stroke=0, fill=1)
        canvas.restoreState()

        sidebar_flow = []

        def sidebar_section(title):
            if sidebar_flow:
                sidebar_flow.append(Spacer(1, 8))
            sidebar_flow.append(para(title, sidebar_heading))
            sidebar_flow.append(HRFlowable(width="100%", thickness=1.1, color=teal, spaceBefore=1, spaceAfter=7))

        photo_value = _safe_text(dp.get("foto"), "")
        photo_path = Path(photo_value) if photo_value else Path(__file__).resolve().parents[2] / "foto.jpeg"
        if doc.page == 1 and photo_path.exists():
            canvas.saveState()
            photo_size = 82
            photo_x = left_x + (left_width - photo_size) / 2
            photo_y = top - photo_size - 4
            path = canvas.beginPath()
            path.circle(photo_x + photo_size / 2, photo_y + photo_size / 2, photo_size / 2)
            canvas.clipPath(path, stroke=0, fill=0)
            canvas.drawImage(str(photo_path), photo_x, photo_y, width=photo_size, height=photo_size, preserveAspectRatio=True, mask="auto")
            canvas.restoreState()
            sidebar_flow.append(Spacer(1, 88))
        if doc.page == 1:
            sidebar_flow.append(para(full_name.upper(), sidebar_name))
            sidebar_flow.extend(para(item, sidebar_role) for item in professions)
            sidebar_section("CONTACTO")
            for value in (phone, email, github, city):
                sidebar_flow.append(para(value, sidebar_text))
            sidebar_section("APTITUDES CLAVE")
            for value in skills[:7]:
                sidebar_flow.append(bullet(value, sidebar_text))
            sidebar_section("SOFTWARE")
            for value in skills[7:19]:
                sidebar_flow.append(bullet(value, sidebar_text))
            sidebar_section("IDIOMAS")
            for value in languages[:4]:
                sidebar_flow.append(para(value, sidebar_text))
        else:
            sidebar_section("EDUCACIÓN")
            for item in training:
                title = _safe_text(item.get("titulo"), "Formación")
                institution = _safe_text(item.get("institucion"), "")
                year = str(item.get("anio", ""))
                sidebar_flow.append(para(title, sidebar_text))
                if institution:
                    sidebar_flow.append(para(institution, sidebar_text))
                if year:
                    sidebar_flow.append(para(year, sidebar_text))
            sidebar_section("CURSOS")
            for value in courses:
                sidebar_flow.append(bullet(value, sidebar_text))
            sidebar_section("INTERESES")
            for value in interests:
                sidebar_flow.append(bullet(value, sidebar_text))

        y = top - 8
        for flowable in sidebar_flow:
            width, height = flowable.wrap(left_width - 22, page_height)
            y -= height
            if y < bottom:
                break
            flowable.drawOn(canvas, left_x + 11 + (left_width - 22 - width) / 2 if isinstance(flowable, Image) else left_x + 11, y)
            y -= 4

    main_story = [
        para(full_name.upper(), name_style),
        para("  |  ".join(title_parts), title_style),
        para(f"{phone}  |  {email}  |  {github}  |  {city}", contact_style),
        para("  |  ".join(str(skill) for skill in skills[:6]), contact_style),
    ]

    def add_section(title):
        main_story.extend([para(title, section_style), HRFlowable(width="100%", thickness=1.2, color=teal, spaceBefore=1, spaceAfter=4)])

    add_section("PERFIL PROFESIONAL")
    main_story.append(para(summary, body_style))
    add_section("EXPERIENCIA PROFESIONAL")
    for experience in experiences:
        item = _experience_block(experience)
        main_story.append(para(item["cargo"], job_style))
        if item["fechas"]:
            main_story.append(para(item["fechas"], date_style))
        main_story.append(para(item["empresa"], body_style))
        main_story.append(para(item["descripcion"], body_style))

    add_section("FORMACIÓN ACADÉMICA")
    for item in training:
        title = _safe_text(item.get("titulo"), "Formación")
        institution = _safe_text(item.get("institucion"), "")
        year = item.get("anio", "")
        main_story.append(para(f"{title} | {institution} | {year}", body_style))
        main_story.append(Spacer(1, 5))

    add_section("COMPETENCIAS TÉCNICAS")
    skill_cells = [bullet(value, body_style) for value in skills]
    skill_rows = []
    for index in range(0, len(skill_cells), 2):
        row = skill_cells[index:index + 2]
        if len(row) == 1:
            row.append(Paragraph("", body_style))
        skill_rows.append(row)
    skills_table = Table(skill_rows, colWidths=[main_width / 2 - 5, main_width / 2 - 5], hAlign="LEFT")
    skills_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    main_story.append(skills_table)
    if courses:
        add_section("FORMACIÓN COMPLEMENTARIA")
        for value in courses:
            main_story.append(bullet(value, body_style))
    if logros:
        add_section("LOGROS DESTACADOS")
        for value in logros:
            main_story.append(bullet(value, body_style))
    frame = Frame(main_x + 10, bottom, main_width - 10, top - bottom, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="main")
    doc = BaseDocTemplate(str(output_path), pagesize=(page_width, page_height), leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0)
    doc.addPageTemplates([PageTemplate(id="model", frames=[frame], onPage=sidebar_block)])
    doc.build(main_story)
    return str(output_path)


def render_cv_to_pdf(profile_or_html, output_pdf_path):
    """Mantiene la API legacy usada por integraciones y pruebas existentes."""
    return render_cv_to_pdf_legacy(profile_or_html, output_pdf_path)


def build_cv_html(cv_data, profile):
    """Retorna un perfil estructurado para que la capa visual se pueda renderizar sin depender de HTML frágil."""
    merged = _normalize_profile(profile if isinstance(profile, dict) else {})
    if isinstance(cv_data, dict):
        for field in ("perfil_profesional", "habilidades", "experiencia", "formacion", "cursos", "logros", "intereses", "titulo_objetivo"):
            if field in cv_data and cv_data[field]:
                if field == "perfil_profesional" and isinstance(cv_data[field], dict):
                    merged[field] = {**merged.get(field, {}), **cv_data[field]}
                else:
                    merged[field] = cv_data[field]
    return merged
