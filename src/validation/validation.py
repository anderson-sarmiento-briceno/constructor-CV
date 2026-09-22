def validate_claims_against_profile(claims, profile):
    """Valida que cada afirmación factual tenga soporte en el perfil maestro.

    La validación no inventa nada: rechaza frases, tecnologías o experiencias que
    no pueden ser rastreadas hasta la base maestra.
    """
    allowed_text = set()

    allowed_text.update(profile.get("habilidades", []))
    allowed_text.update(profile.get("tecnologias", []))
    allowed_text.update(profile.get("certificaciones", []))
    allowed_text.update(profile.get("idiomas", []))

    for exp in profile.get("experiencia", []):
        empresa = exp.get("empresa", "")
        cargo = exp.get("cargo", "")
        if empresa:
            allowed_text.add(empresa)
        if cargo:
            allowed_text.add(cargo)
        if empresa and cargo:
            allowed_text.add(f"{cargo} en {empresa}")

    approved = []
    rejected = []

    for claim in claims:
        normalized = claim.strip()
        if not normalized:
            continue

        if any(token.lower() in claim.lower() for token in allowed_text):
            approved.append(normalized)
        else:
            rejected.append(normalized)

    return {
        "approved": len(rejected) == 0,
        "approved_claims": approved,
        "rejected": rejected,
    }
