# CV Dinámico Personalizado por Oferta

Proyecto para generar CVs personalizados orientados a una oferta laboral, usando una base maestra de información del candidato y validación anti-alucinación.

## Objetivo

- Extraer requisitos de una oferta en Word.
- Compararlos con un perfil maestro.
- Priorizar experiencia real relevante.
- Redactar un CV adaptado sin inventar hechos.
- Exportar a PDF ATS-friendly.

## Estructura

- `CVS/`: currículos históricos y documentos de respaldo.
- `ofertas/`: ofertas en formato `.docx`.
- `src/`: lógica del extractor, matching y validación.
- `tests/`: pruebas para la validación base.

## Requisitos

```bash
pip install -r requirements.txt
```

## Ejecutar pruebas

```bash
pytest -q
```

## Nota

Este primer scaffold implementa la base del motor de validación anti-alucinación y la estructura inicial del proyecto. La siguiente fase es integrar extracción de `.docx`, matching semántico y generación del CV final.
