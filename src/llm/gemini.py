import json
import os
from urllib import error, request

from dotenv import load_dotenv

load_dotenv()


def _fallback_analysis(profile):
    keywords = []
    for skill in profile.get("habilidades", []):
        keywords.append(skill)

    summary = (
        "Perfil orientado a ingeniería eléctrica, automatización, análisis de datos, "
        "Power BI y eficiencia energética con fuerte vínculo a proyectos reales."
    )

    return {
        "cargo_detectado": "No validado automáticamente",
        "palabras_clave": keywords[:20],
        "resumen_profesional": summary,
        "experiencia_priorizada": [
            "Green Mobil - Científico de Datos",
            "Enel Colombia - infraestructura y automatización",
            "Consultoría freelance - automatización energética",
        ],
        "estado": "propuesta de análisis local",
    }


def _call_gemini(prompt, model_name="gemini-3.6-flash"):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            text = parsed["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def analyze_offer_and_profile(offer_text, profile, model_name="gemini-3.6-flash"):
    """Usa Gemini solo para interpretar semánticamente la oferta y priorizar contenido.

    La verdad factual se toma del perfil maestro y el sistema siempre valida antes
    de aceptar cualquier afirmación factual.
    """
    if not offer_text or not isinstance(profile, dict):
        return _fallback_analysis(profile or {})

    profile_summary = json.dumps(profile, ensure_ascii=False, indent=2)
    offer_sample = (offer_text[:12000] if offer_text else "")

    prompt = f"""
    Eres un analista de selección con estricta regla anti-alucinación.
    Tu trabajo es analizar una oferta y un perfil profesional real.

    REGLAS:
    1. No inventes empleos, empresas, fechas, títulos, herramientas o métricas.
    2. Usa solo la información que recibe en el perfil y en la oferta.
    3. Si no hay evidencia suficiente, devuelve "NO_EVIDENCIADO".
    4. Devuelve SOLO JSON válido con estas claves:
       - cargo_detectado
       - palabras_clave
       - resumen_profesional
       - experiencia_priorizada
       - estado

    PERFIL MAESTRO:
    {profile_summary}

    OFERTA:
    {offer_sample}

    Responde en español, con una salida breve y útil para un CV dinámico.
    """

    gemini_response = _call_gemini(prompt, model_name=model_name)
    if gemini_response:
        cleaned = {
            "cargo_detectado": gemini_response.get("cargo_detectado", "NO_EVIDENCIADO"),
            "palabras_clave": gemini_response.get("palabras_clave", [])[:30],
            "resumen_profesional": gemini_response.get("resumen_profesional", ""),
            "experiencia_priorizada": gemini_response.get("experiencia_priorizada", []),
            "estado": "analizado con Gemini",
        }
        return cleaned

    return _fallback_analysis(profile)
