"""Redacción final con Gemini: perfil profesional y experiencias.

Se ejecuta al final, cuando Groq ya hizo todo el proceso. Hay dos llamadas, cada una con
su propio prompt: una redacta el perfil profesional y otra reescribe las experiencias.
El texto de Gemini reemplaza al de Groq; si Gemini no responde con ninguna clave ni con
ningún modelo, se conservan los textos de Groq y se devuelve un aviso.

Las claves se leen de APY_KEY_GEMINI y APY_KEY_GEMINI_2 en .env (la segunda se usa si la
primera se queda sin cupo) y solo viajan en una cabecera: nunca se imprimen. Solo se envían
los textos, los hechos profesionales necesarios y las prioridades de la oferta; nunca
nombre, contacto ni foto.
"""
import json
import os
import re
import time
from urllib import error, request

from dotenv import load_dotenv

from src.llm.llm import (
    _ECHO_STEM,
    _compact,
    _compact_profile_for_summary,
    _misplaced_metric_issues,
    _significant_terms,
    _stem,
    _stems_of,
    offer_terms_missing_from_profile,
)

load_dotenv()

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_KEY_VARIABLES = ("APY_KEY_GEMINI", "APY_KEY_GEMINI_2")
# Modelo principal y de respaldo: el principal se prueba con cada clave y, solo si ninguna
# funciona, se pasa al de respaldo (también con cada clave).
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"

_SHARED_RULES = """PRESERVACIÓN RIGUROSA:
- No agregues nada que no esté en el material recibido: ni herramientas, ni sectores, ni responsabilidades, ni logros, ni cifras, ni el tamaño o tipo de un equipo, ni el propósito o el beneficio de una acción si el original no lo dice (por ejemplo, no añadas "para la continuidad del servicio" o "seguridad institucional").
- No exageres: no conviertas "aporté a" o "insumo para" en "logré" o "permití", ni "construí" en "lideré". No cambies el significado de una métrica.
- No agregues adjetivos inflados ("avanzado", "sofisticado", "robusto", "estratégico", "riguroso", "integral", "de alta precisión", "de alto impacto", "estrictos") ni muletillas ("garantizando", "apalancado", "articulando", "soluciones escalables", "decisiones estratégicas", "mi capacidad para", "mi ventaja competitiva").
- PALABRAS PROHIBIDAS: nunca uses las palabras de la lista que se te entrega (aparecen en la oferta pero no en mi perfil), ni sus variantes. Las prioridades de la oferta solo indican qué destacar primero.
- Ortografía impecable, incluidos los pretéritos ("optimicé", "automaticé", "organicé"). No uses punto y coma para encadenar ideas.
- Copia los nombres propios, siglas y nombres de herramientas exactamente como aparecen, incluidos sus símbolos: "PSS/E", "MT/BT", "SQL / PostgreSQL", "ISO 50001". Nunca cambies una barra "/" por "y".

Responde solo con el JSON pedido."""

_PROFILE_SYSTEM = f"""Actúa como un consultor experto en redacción ejecutiva de hojas de vida en español. Redactas el PERFIL PROFESIONAL de un CV: el párrafo que un reclutador lee primero.

CÓMO DEBE SER EL PERFIL:
- Entre 80 y 110 palabras, en 4 o 5 oraciones de menos de 25 palabras, en primera persona y en presente.
- Oración 1: "Soy" + mis profesiones (si la oferta corresponde a una de ellas, nómbrala junto a la de mayor trayectoria, por ejemplo "Soy [profesión de mayor trayectoria] y [profesión de la oferta]") + mi formación (especialización y estudios que aparezcan en el material). Es obligatorio incluir la formación.
- Si hay años de experiencia en el material, son mi trayectoria TOTAL y se describen como en el material, combinando las áreas que allí aparecen (por ejemplo, "más de N años de trayectoria integrando [área 1] y [área 2]"). Nunca los atribuyas a una sola área o profesión ("15 años en analítica" está mal si el material dice que se combinaron varias áreas).
- Oraciones 2 y 3: dos o tres fortalezas reales que respondan a las prioridades de la oferta, contadas como capacidades (qué hago y para qué sirve), no como lista de proyectos.
- Como máximo 5 herramientas, solo de las que aparecen en el material, elegidas según la oferta. Sin nombres de clases de librerías.
- Oración final: el diferencial real que muestra el material, sin exagerar.
- Sin porcentajes ni cifras de resultados (van en la sección de experiencia). Sin repetir proyectos concretos de las experiencias.
- No encadenes más de dos "y" en una oración, no dejes listas unidas solo con comas y no repitas palabras.
- Si el material marca requisitos de la oferta como no evidenciados, no los menciones ni los insinúes.
- Las prácticas de trabajo (análisis exploratorio, feature engineering, validación de modelos) se mencionan como mucho UNA vez en el perfil, juntas y como capacidad general: las experiencias ya dan el detalle.
- PALABRAS CLAVE RECOMENDADAS: son capacidades que están a la vez en mi perfil y en la oferta. Usa de forma natural solo las que encajen (no todas y nunca en forma de lista) y preséntalas como capacidades generales: no las atribuyas a una empresa, un proyecto o un resultado concreto.

EJEMPLO DE ESTILO (otra persona y otra profesión: imita solo el tono y la estructura, nunca sus datos):
"Soy Arquitecta, especialista en vivienda social, con más de diez años de trayectoria en proyectos públicos. Diseño conjuntos habitacionales que equilibran costo, normativa y calidad de vida. Coordino equipos de obra y consultores para cumplir cronogramas exigentes. Trabajo con AutoCAD, Revit y Excel para presupuestar con precisión. Mi diferencial es entender a la vez el diseño, la obra y a las comunidades que la habitan."

{_SHARED_RULES}"""

_EXPERIENCE_SYSTEM = f"""Actúa como un consultor experto en redacción ejecutiva de hojas de vida en español. Tu objetivo es REEVALUAR Y REESCRIBIR PROFUNDAMENTE descripciones de experiencia que ya están escritas, elevando el tono ejecutivo para que suenen sobrias, fluidas y de alto impacto, SIN cambiar ni agregar hechos.

REESTRUCTURA:
- Reformulación sintáctica real: no te limites a unir oraciones. Cambia la estructura de las frases, varía los verbos de acción ("Lideré", "Impulsé", "Estructuré", "Desplegué", "Automaticé") y ordena las ideas de lo más relevante para la oferta a lo complementario.
- Abre la descripción con un verbo de acción directo en primera persona. Usa como máximo UN conector de transición ("Además", "Asimismo", "Paralelamente") por descripción y varía la forma de enlazar las ideas. No uses "mientras" ni "paralelamente" si el original no dice que las acciones fueron simultáneas.
- Cada oración tiene entre 15 y 30 palabras: combina en una misma oración las ideas relacionadas y nunca escribas frases sueltas de menos de 10 palabras ("Automaticé el procesamiento." está mal).
- La acción y su resultado van SIEMPRE en la misma oración, tal como en el original (por ejemplo, "Desarrollé modelos de riesgo que redujeron un 40% los accidentes", nunca "Desarrollé modelos de riesgo. Logré reducir un 40% los accidentes.").
- Cada cifra se queda con la acción exacta que la produjo según el original, aunque otra acción aparezca en la misma frase: si el original dice "desplegué modelos y optimicé el código, lo que redujo un X% el tiempo", la cifra es de optimizar el código, no de desplegar modelos. Nunca omitas la acción que produjo la cifra.
- Usa conectores de causa-efecto SOLO cuando el original ya establece esa relación. Nunca inventes que una acción causó un resultado.
- Recibes todas las experiencias juntas: coordínalas. Una práctica común a varias experiencias (por ejemplo, análisis exploratorio, feature engineering o validación de modelos) se menciona de forma explícita en UNA sola experiencia, la más relevante para la oferta; en las demás no repitas esa frase. Tampoco repitas entre experiencias la misma estructura de oración ni el mismo verbo inicial.
- Cada experiencia trae "texto_actual" (el borrador a reescribir) y "fuente" (mi perfil maestro, que es la verdad). Si el borrador omitió una herramienta, acción o cifra de la fuente que sea relevante para la oferta, recupérala; si la cambió (por ejemplo, "incidentes" donde la fuente dice "accidentes", o una cifra unida a otra acción), corrígela según la fuente. Usa SOLO hechos de esa misma experiencia: nunca tomes datos de otra.
- Primera persona del singular y tiempo pasado.
- Conserva sin alteración todas las tecnologías, herramientas, normas y estándares, y todas las cifras y métricas, cada una unida al mismo resultado y a la misma acción que en el original. No elimines ninguna.
- Cada descripción es UN SOLO PÁRRAFO continuo, sin listas ni títulos, de entre 80 y 130 palabras. El límite de 130 palabras es estricto: la fuente tiene más hechos de los que caben, así que elige los más relevantes para la oferta y deja fuera el resto. Si recuperas algo de la fuente, quita a cambio lo menos relevante. No escribas el nombre de la empresa, el cargo ni las fechas: ya aparecen en el encabezado.

EJEMPLO DE TRANSFORMACIÓN (fíjate en que no se agrega ningún hecho):
- ENTRADA: "Hice proyectos de software con Python y Django. Reduje errores en 20%. Usé PostgreSQL para las bases de datos y lideré 5 personas."
- SALIDA: "Lideré a un equipo de 5 personas en proyectos de software con Python y Django, sobre bases de datos PostgreSQL. Reduje los errores en un 20%."

{_SHARED_RULES}"""


class GeminiUnavailable(RuntimeError):
    """Gemini no se pudo usar. El mensaje nunca incluye la clave."""


def gemini_model():
    """Modelo principal: GEMINI_MODEL en .env o el valor por defecto de este módulo."""
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL


def gemini_models():
    """Modelos a probar en orden: el principal y el de respaldo (GEMINI_FALLBACK_MODEL)."""
    fallback = os.getenv("GEMINI_FALLBACK_MODEL", DEFAULT_GEMINI_FALLBACK_MODEL).strip()
    return [gemini_model()] + ([fallback] if fallback and fallback != gemini_model() else [])


def _gemini_keys():
    """(etiqueta, clave) de cada clave configurada, en orden; la etiqueta nunca es la clave."""
    return [
        (f"clave {index}", os.getenv(name, "").strip())
        for index, name in enumerate(GEMINI_KEY_VARIABLES, start=1)
        if os.getenv(name, "").strip()
    ]


def gemini_enabled():
    """Activo si hay al menos una clave y GEMINI_POLISH no es "0"."""
    return bool(_gemini_keys()) and os.getenv("GEMINI_POLISH", "1").strip() != "0"


def _error_message(exc):
    try:
        return str(json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", ""))[:200]
    except (ValueError, AttributeError, OSError):
        return ""


def _call_gemini(system, user, model, key, retries=3):
    """Una llamada a Gemini en modo JSON. Reintenta solo si el modelo está saturado (503).

    Temperatura 0.7 y top_p 0.9 para que reformule de verdad la sintaxis.
    """
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.7, "topP": 0.9, "responseMimeType": "application/json"},
    }).encode("utf-8")
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": "cv-dinamico/1.0"}
    timeout = float(os.getenv("GEMINI_TIMEOUT", "").strip() or 90)
    url = GEMINI_URL.format(model=model)
    for attempt in range(retries + 1):
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            return json.loads("".join(part.get("text", "") for part in parts if not part.get("thought")))
        except error.HTTPError as exc:
            message = _error_message(exc)
            if exc.code == 503 and attempt < retries:
                time.sleep(5 * 2 ** attempt)  # 5, 10 y 20 s: a veces responde tras ~18 s
                continue
            if exc.code == 429:
                raise GeminiUnavailable(f"sin cupo (HTTP 429): {message}") from None
            raise GeminiUnavailable(f"HTTP {exc.code}: {message}") from None
        except error.URLError as exc:
            raise GeminiUnavailable(f"sin conexión ({exc.reason})") from None
        except TimeoutError:
            raise GeminiUnavailable(f"no respondió en {timeout:.0f} s") from None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeminiUnavailable(f"respuesta no válida ({type(exc).__name__})") from None
    raise GeminiUnavailable("sigue saturado tras los reintentos")


def _ask_gemini(system, user, models=None):
    """Prueba cada modelo (por defecto el principal y luego el de respaldo) con cada clave.

    Devuelve (resultado, "modelo con clave N", fallos previos) o lanza GeminiUnavailable
    con todos los motivos.
    """
    failures = []
    for model in models or gemini_models():
        for label, key in _gemini_keys():
            try:
                return _call_gemini(system, user, model, key), f"{model} con {label}", failures
            except GeminiUnavailable as exc:
                failures.append(f"{model} con {label}: {exc}")
    raise GeminiUnavailable(" | ".join(failures) or "no hay claves de Gemini configuradas")


def _forbidden_line(forbidden):
    return "PALABRAS PROHIBIDAS (están en la oferta pero no en mi perfil): " + (", ".join(forbidden) or "ninguna")


def recommended_keywords(profile, offer_text, limit=7):
    """Capacidades del perfil que la oferta también pide (todas sus palabras aparecen en la
    oferta). Solo salen del perfil, así que usarlas no atribuye nada que no se tenga.

    Orden: primero las que aparecen tal cual en la oferta; luego por la posición de su
    palabra más específica (la que aparece más tarde). Como máximo 2 que empiecen por la
    misma palabra, para no llenar la lista de variantes ("Modelos de...")."""
    offer_lower = (offer_text or "").casefold()
    offer_stems = _stems_of(offer_text, _ECHO_STEM)
    candidates = list(dict.fromkeys(
        str(item).strip()
        for key in ("aptitudes", "competencias", "software", "habilidades")
        for item in profile.get(key, []) if str(item).strip()
    ))
    ranked = []
    for item in candidates:
        terms = _significant_terms(item)
        stems = {_stem(term, _ECHO_STEM) for term in terms}
        if not stems or not stems <= offer_stems:
            continue
        exact = item.casefold() in offer_lower
        positions = [offer_lower.find(term) for term in terms if term in offer_lower]
        position = offer_lower.find(item.casefold()) if exact else max(positions, default=len(offer_lower))
        ranked.append((not exact, position, item))
    selected, first_words = [], {}
    for _, _, item in sorted(ranked):
        first_word = item.split()[0].casefold()
        if first_words.get(first_word, 0) >= 2:
            continue
        first_words[first_word] = first_words.get(first_word, 0) + 1
        selected.append(item)
    return selected[:limit]


def _polish_profile(summary, priorities, profile, unevidenced, forbidden, recommended):
    material = {
        "perfil_actual": summary,
        "hechos_del_perfil": _compact_profile_for_summary(profile),
        "software": profile.get("software", []),
        "requisitos_no_evidenciados": unevidenced or [],
    }
    prompt = f"""TAREA: redacta mi perfil profesional para esta oferta, usando solo el MATERIAL.

Devuelve JSON con esta forma:
{{"resumen":"..."}}

PRIORIDADES DE LA OFERTA (solo para decidir qué destacar): {"; ".join(str(item) for item in priorities) or "ninguna"}
PALABRAS CLAVE RECOMENDADAS (están en mi perfil y en la oferta): {", ".join(recommended) or "ninguna"}
{_forbidden_line(forbidden)}

MATERIAL:
{_compact(material)}"""
    result, used, failures = _ask_gemini(_PROFILE_SYSTEM, prompt)
    return str(result.get("resumen", "")).strip() if isinstance(result, dict) else "", used, failures


def _source_experience(item, profile):
    """Descripción original, logros y herramientas de esa experiencia en el perfil maestro."""
    for source in profile.get("experiencia", []):
        if source.get("empresa") == item.get("empresa") and source.get("cargo") == item.get("cargo"):
            return {key: source.get(key) for key in ("descripcion", "logros", "herramientas") if source.get(key)}
    return {}


def _polish_experiences(experiences, descriptions, priorities, forbidden, profile):
    blocks = [{"indice": index, "cargo": item.get("cargo", ""), "fechas": item.get("fechas", ""),
               "texto_actual": text, "fuente": _source_experience(item, profile)}
              for index, (item, text) in enumerate(zip(experiences, descriptions))]
    prompt = f"""TAREA: reescribe en profundidad cada descripción de experiencia, sin cambiar sus hechos.

Devuelve JSON con esta forma:
{{"experiencias":[{{"indice":0,"descripcion":"..."}}]}}

PRIORIDADES DE LA OFERTA (solo para decidir qué destacar primero): {"; ".join(str(item) for item in priorities) or "ninguna"}
{_forbidden_line(forbidden)}

EXPERIENCIAS (texto_actual = borrador a reescribir; fuente = mi perfil maestro, la verdad):
{json.dumps(blocks, ensure_ascii=False)}"""
    result, used, failures = _ask_gemini(_EXPERIENCE_SYSTEM, prompt)
    proposals = {}
    items = result.get("experiencias") if isinstance(result, dict) else None
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("indice"), int):
            proposals[item["indice"]] = str(item.get("descripcion", "")).strip()
    return proposals, used, failures


# ---------------------------------------------------------------------------
# Revisión local (gratis) de lo que redactó Gemini en las experiencias y, solo si hay
# errores, una única llamada de corrección con las experiencias afectadas.
# ---------------------------------------------------------------------------
_PERCENT = r"\d+(?:[.,]\d+)?%"
# Palabras con las que se describe cualquier cambio en una métrica: no indican un cambio de
# significado aunque la fuente use otra ("disminución" en lugar de "reducción").
_CHANGE_WORDS = {"reducción", "disminución", "mejora", "aumento", "incremento", "ahorro", "porcentaje", "casos"}
_VERB_ENDINGS = ("ando", "iendo", "endo", "aron", "ieron", "ó", "é", "í", "ar", "er", "ir")


def _source_sentences(source):
    text = " ".join([str(source.get("descripcion", ""))] + [str(item) for item in source.get("logros", [])])
    return [re.sub(r"(\d)\s+%", r"\1%", sentence) for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]


def _mentioned_tools(text, tools):
    lowered = (text or "").casefold()
    return {
        tool for tool in tools
        if tool and re.search(r"(?<!\w)" + re.escape(str(tool).casefold()) + r"(?!\w)", lowered)
    }


def _review_experience(text, source, other_tools):
    """Errores de hechos en una experiencia redactada por Gemini, comparada con su fuente."""
    issues = []
    text = re.sub(r"(\d)\s+%", r"\1%", text or "")
    sentences_source = _source_sentences(source)
    source_text = " ".join(sentences_source)
    source_stems = _stems_of(source_text, _ECHO_STEM)

    new_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text)) - set(re.findall(r"\d+(?:[.,]\d+)?", source_text))
    if new_numbers:
        issues.append("cifras que no están en la fuente: " + ", ".join(sorted(new_numbers)))

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        metrics = set(re.findall(_PERCENT, sentence))
        # Varias cifras en una oración solo si en la fuente también van juntas.
        if len(metrics) > 1 and not any(all(metric in src for metric in metrics) for src in sentences_source):
            issues.append(f"une cifras que en la fuente son de acciones distintas ({', '.join(sorted(metrics))}): «{sentence.strip()}»")
        # Palabras junto a cada cifra que no aparecen en la fuente (p. ej., "incidentes" por "accidentes").
        words = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+|" + _PERCENT, sentence)
        for position, word in enumerate(words):
            if not word.endswith("%"):
                continue
            for term in words[max(0, position - 6): position + 7]:
                lowered = term.casefold()
                if (term.endswith("%") or len(lowered) < 5 or lowered in _CHANGE_WORDS
                        or lowered.endswith(_VERB_ENDINGS) or lowered not in _significant_terms(term)):
                    continue
                if _stem(lowered, _ECHO_STEM) not in source_stems:
                    issues.append(f"junto a la cifra {word} aparece «{term}», que no está en la fuente")

    issues.extend(_misplaced_metric_issues(text, source))
    foreign = _mentioned_tools(text, other_tools) - _mentioned_tools(source_text, other_tools)
    if foreign:
        issues.append("menciona herramientas de otra experiencia: " + ", ".join(sorted(foreign)))
    return list(dict.fromkeys(issues))


def _correct_experiences(flagged):
    """Una sola llamada para corregir solo las experiencias con errores. Usa primero el
    modelo de respaldo (el ligero, con más cupo gratuito) para gastar poco."""
    prompt = f"""TAREA: corrige SOLO los problemas indicados en cada descripción, cambiando lo mínimo y conservando su estilo y su longitud.

Devuelve JSON con esta forma:
{{"experiencias":[{{"indice":0,"descripcion":"..."}}]}}

DESCRIPCIONES CON PROBLEMAS (fuente = mi perfil maestro, la verdad):
{json.dumps(flagged, ensure_ascii=False)}"""
    models = list(dict.fromkeys(reversed(gemini_models())))
    result, used, failures = _ask_gemini(_EXPERIENCE_SYSTEM, prompt, models)
    corrected = {}
    items = result.get("experiencias") if isinstance(result, dict) else None
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("indice"), int) and str(item.get("descripcion", "")).strip():
            corrected[item["indice"]] = str(item["descripcion"]).strip()
    return corrected, used, failures


def _review_and_correct(experiences, final_descriptions, proposals, profile, report):
    """Revisa localmente lo que redactó Gemini y, si hay errores, pide UNA corrección.
    El texto final siempre es de Gemini; lo que siga mal queda como aviso para revisar."""
    sources = [_source_experience(item, profile) for item in experiences]
    all_tools = [set(source.get("herramientas", [])) for source in sources]

    def review(index):
        other_tools = set().union(*(tools for i, tools in enumerate(all_tools) if i != index)) - all_tools[index]
        return _review_experience(final_descriptions[index], sources[index], other_tools)

    flagged = {index: review(index) for index in proposals if index < len(experiences) and sources[index]}
    flagged = {index: issues for index, issues in flagged.items() if issues}
    report["correccion"] = {"revisadas": len(proposals), "con_errores": len(flagged)}
    if not flagged:
        return

    blocks = [{"indice": index, "texto": final_descriptions[index], "problemas": issues, "fuente": sources[index]}
              for index, issues in flagged.items()]
    try:
        corrected, used, failures = _correct_experiences(blocks)
        report["correccion"]["modelo"] = used
        report["intentos_fallidos"] += failures
    except GeminiUnavailable as exc:
        corrected = {}
        report["avisos"].append(f"No se pudo pedir la corrección a Gemini ({exc}).")
    for index, text in corrected.items():
        if index in flagged:
            final_descriptions[index] = text
    for index in flagged:
        remaining = review(index)
        if remaining:
            name = experiences[index].get("empresa", f"experiencia {index}")
            report["avisos"].append(f"Revisa {name} antes de enviar: " + "; ".join(remaining))


def polish_with_gemini(summary, experiences, priorities, profile, offer_text=None, unevidenced=None):
    """Redacta con Gemini el perfil profesional (un prompt) y las experiencias (otro prompt).

    Devuelve (resumen, descripciones, reporte). El texto de Gemini reemplaza al de Groq;
    solo se conserva el de Groq si Gemini no responde o devuelve un bloque vacío.
    """
    descriptions = [str(item.get("descripcion", "")).strip() for item in experiences]
    # avisos: solo cuando un bloque se queda sin Gemini. intentos_fallidos: combinaciones de
    # modelo y clave que fallaron antes de que otra respondiera (informativo).
    report = {"estado": "", "perfil": "", "experiencias": "", "avisos": [], "intentos_fallidos": [], "bloques": []}
    if not gemini_enabled():
        report["estado"] = "desactivado"
        return summary, descriptions, report

    # Palabras de la oferta que no aparecen en ninguna parte del perfil (calculadas localmente).
    forbidden = offer_terms_missing_from_profile(offer_text, profile) if offer_text else []
    recommended = recommended_keywords(profile, offer_text) if offer_text else []
    report["palabras_prohibidas"] = forbidden
    report["palabras_clave_recomendadas"] = recommended

    final_summary = summary
    try:
        polished, used, failures = _polish_profile(summary, priorities, profile, unevidenced, forbidden, recommended)
        report["perfil"] = used
        report["intentos_fallidos"] += failures
        if polished:
            final_summary = polished
        report["bloques"].append({"bloque": "perfil", "resultado": "redactado por Gemini" if polished else "Gemini lo devolvió vacío; se conserva el de Groq"})
    except GeminiUnavailable as exc:
        report["avisos"].append(f"Perfil: Gemini no disponible ({exc}); se conserva el texto de Groq.")
        report["bloques"].append({"bloque": "perfil", "resultado": "sin Gemini; se conserva el de Groq"})

    final_descriptions = list(descriptions)
    try:
        proposals, used, failures = _polish_experiences(experiences, descriptions, priorities, forbidden, profile)
        report["experiencias"] = used
        report["intentos_fallidos"] += failures
        for index, item in enumerate(experiences):
            polished = proposals.get(index, "")
            if polished:
                final_descriptions[index] = polished
            report["bloques"].append({
                "bloque": item.get("empresa", f"experiencia {index}"),
                "resultado": "redactado por Gemini" if polished else "Gemini lo devolvió vacío; se conserva el de Groq",
            })
        _review_and_correct(experiences, final_descriptions, proposals, profile, report)
    except GeminiUnavailable as exc:
        report["avisos"].append(f"Experiencias: Gemini no disponible ({exc}); se conservan los textos de Groq.")
        for index, item in enumerate(experiences):
            report["bloques"].append({"bloque": item.get("empresa", f"experiencia {index}"),
                                      "resultado": "sin Gemini; se conserva el de Groq"})

    used_any = bool(report["perfil"] or report["experiencias"])
    report["estado"] = "aplicado" if used_any else "no_disponible"
    return final_summary, final_descriptions, report
