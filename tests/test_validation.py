from src.validation.validation import validate_claims_against_profile


def test_validate_claims_allows_supported_claims():
    profile = {
        "habilidades": ["Python", "Power BI", "SQL"],
        "experiencia": [
            {"empresa": "Green Mobil", "cargo": "Científico de Datos"},
            {"empresa": "Enel", "cargo": "Ingeniero"},
        ],
    }

    claims = [
        "Python",
        "Power BI",
        "Científico de Datos en Green Mobil",
    ]

    result = validate_claims_against_profile(claims, profile)
    assert result["approved"] is True
    assert result["rejected"] == []


def test_validate_claims_rejects_unknown_claims():
    profile = {
        "habilidades": ["Python", "Power BI"],
        "experiencia": [{"empresa": "Enel", "cargo": "Ingeniero"}],
    }

    claims = [
        "Python",
        "TensorFlow",
        "Cargo inventado en Empresa Falsa",
    ]

    result = validate_claims_against_profile(claims, profile)
    assert result["approved"] is False
    assert "TensorFlow" in result["rejected"]
    assert "Cargo inventado en Empresa Falsa" in result["rejected"]
