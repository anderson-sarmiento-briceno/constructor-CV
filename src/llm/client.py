"""Cliente mínimo para la API de Groq (formato compatible con OpenAI).

La clave se lee de APY_KEY en .env y solo viaja en el header Authorization:
nunca se imprime, se registra ni aparece en los mensajes de error.
"""
import json
import os
import re
import time
from urllib import error, request

from dotenv import load_dotenv

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
# "medium" sigue mejor las reglas de redacción que "low"; "high" puede superar por sí
# sola el límite gratuito de 8.000 tokens por minuto en la llamada de experiencias.
DEFAULT_REASONING_EFFORT = "medium"
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_WAIT_SECONDS = 60


class LLMError(RuntimeError):
    """Fallo al consultar el modelo. El mensaje nunca incluye la clave."""


def model_name():
    """Modelo activo: GROQ_MODEL en .env o el valor por defecto de este módulo."""
    return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def _api_key():
    key = os.getenv("APY_KEY", "").strip()
    if not key:
        raise LLMError("Falta la variable APY_KEY en .env")
    return key


def _error_detail(exc):
    """Mensaje de error que devuelve Groq (sin headers, por lo tanto sin la clave)."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        return str(body.get("error", {}).get("message", ""))[:300]
    except (ValueError, AttributeError, OSError):
        return ""


def _wait_from_message(detail):
    """Espera que Groq indica en el texto del error ("try again in 1m2.5s", "12.58s", "450ms")."""
    match = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)(ms|s)", detail or "")
    if not match:
        return None
    minutes, amount, unit = match.groups()
    seconds = float(amount) / 1000 if unit == "ms" else float(amount)
    return seconds + 60 * int(minutes or 0)


def _wait_seconds(exc, attempt, detail=""):
    """Espera antes de reintentar: cabecera retry-after, o la que dice el mensaje de Groq
    (con un segundo de margen), o una espera creciente si no hay ninguna."""
    try:
        wait = float(exc.headers.get("retry-after")) if exc.headers else None
    except (TypeError, ValueError):
        wait = None
    if wait is None:
        from_message = _wait_from_message(detail)
        wait = from_message + 1 if from_message is not None else 2 ** attempt
    return min(max(wait, 1), _MAX_WAIT_SECONDS)


def chat(system, user, json_mode=True, max_retries=3):
    """Envía un mensaje system + user y devuelve un dict (json_mode) o el texto."""
    payload = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    # Modelos de razonamiento (gpt-oss, qwen3): el razonamiento no se devuelve, para no
    # gastar tokens de más. GROQ_REASONING_EFFORT vacía = no enviar estos campos.
    reasoning_effort = os.getenv("GROQ_REASONING_EFFORT", DEFAULT_REASONING_EFFORT).strip()
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
        payload["include_reasoning"] = False

    data = json.dumps(payload).encode("utf-8")
    timeout = float(os.getenv("GROQ_TIMEOUT", "").strip() or 60)
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "User-Agent": "cv-dinamico/1.0",
    }

    for attempt in range(max_retries + 1):
        req = request.Request(GROQ_URL, data=data, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            content = parsed["choices"][0]["message"]["content"] or ""
            return json.loads(content) if json_mode else content.strip()
        except error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code in _RETRY_STATUS and attempt < max_retries:
                time.sleep(_wait_seconds(exc, attempt, detail))
                continue
            # 400 "Failed to generate JSON": el modelo produjo un JSON inválido en esa
            # generación; es ocasional, así que se repite la misma petición.
            if exc.code == 400 and "json" in detail.casefold() and attempt < max_retries:
                time.sleep(1)
                continue
            raise LLMError(f"Groq respondió HTTP {exc.code}" + (f": {detail}" if detail else "")) from None
        except error.URLError as exc:
            raise LLMError(f"No se pudo conectar con Groq ({exc.reason})") from None
        except TimeoutError:
            raise LLMError(f"Groq no respondió en {timeout:.0f} s") from None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"Respuesta de Groq no válida: {type(exc).__name__}") from None
    raise LLMError("Groq no respondió tras los reintentos")
