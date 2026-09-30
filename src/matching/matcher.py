import re

SEMANTIC_MAP = {
    "python": {"python"},
    "powerbi": {"power bi", "powerbi", "bi"},
    "sql": {"sql"},
    "postgresql": {"postgresql", "postgres"},
    "etl": {"etl", "extract transform load"},
    "machine learning": {"machine learning", "ml"},
    "data analyst": {"data analyst", "analista de datos"},
    "data scientist": {"data scientist", "cientifico de datos", "científico de datos"},
    "bi": {"bi", "business intelligence"},
    "energia": {"energia", "energía", "energy"},
    "eficiencia energetica": {"eficiencia energetica", "eficiencia energética"},
    "movilidad electrica": {"movilidad electrica", "movilidad eléctrica"},
    "automatizacion": {"automatizacion", "automatización", "automation"},
    "analisis datos": {"analisis de datos", "análisis de datos"},
}


def normalize_text(value):
    if not value:
        return ""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9áéíóúüñ\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_profile_keywords(profile):
    keywords = set()
    for item in profile.get("habilidades", []):
        keywords.add(normalize_text(item))
    for item in profile.get("certificaciones", []):
        keywords.add(normalize_text(item))
    for item in profile.get("experiencia", []):
        for field in ("empresa", "cargo", "descripcion"):
            keywords.add(normalize_text(item.get(field, "")))
    return keywords


def classify_requirement(requirement, profile):
    req_norm = normalize_text(requirement)
    if not req_norm:
        return "NO_EVIDENCIADO"

    profile_keywords = build_profile_keywords(profile)
    expanded_keywords = set(profile_keywords)
    for key in list(profile_keywords):
        if len(key) > 0:
            expanded_keywords.add(key)

    for alias in SEMANTIC_MAP:
        if req_norm in SEMANTIC_MAP[alias]:
            for candidate in SEMANTIC_MAP[alias]:
                if candidate in expanded_keywords:
                    return "MATCH_SEMANTICO"

    for candidate in expanded_keywords:
        if candidate and (req_norm in candidate or candidate in req_norm):
            return "MATCH_EXACTO"

    req_tokens = set(req_norm.split())
    overlap = req_tokens & {token for item in profile_keywords for token in item.split()}
    if overlap:
        return "MATCH_PARCIAL"

    return "NO_EVIDENCIADO"


def classify_requirements(requirements, profile):
    results = []
    for item in requirements:
        results.append({
            "requisito": item,
            "estado": classify_requirement(item, profile),
        })
    return results
