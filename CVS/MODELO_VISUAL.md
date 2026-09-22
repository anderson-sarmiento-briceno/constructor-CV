# Especificacion visual del CV modelo

Referencia: `CV_Anderson_Sarmiento_Modelo.pdf`

## Geometria

- Pagina: carta, 612 x 792 pt.
- El documento usa dos paginas.
- Columna lateral izquierda: fondo azul/teal continuo, aproximadamente desde x=28 hasta x=194.
- Columna principal: fondo blanco, comienza aproximadamente en x=218.
- No debe dibujarse una linea vertical separando las columnas.
- Las secciones se separan con lineas horizontales finas, cortas y en azul grisaceo.

## Colores de referencia

- Fondo sidebar: teal azul oscuro, aproximacion de trabajo `#173F4F`.
- Titulos principales y nombres: azul oscuro `#173F4F`.
- Subtitulos y acentos: teal medio `#2E6572`.
- Texto principal: gris carbon `#1F2933`.
- Metadatos: gris azulado `#63727A`.
- Lineas divisorias: gris teal claro `#B8C8CC`.
- Texto del sidebar: blanco.

Los colores se mantienen centralizados en `src/rendering/pdf_renderer.py` y no deben variar segun la oferta.

## Sidebar izquierdo

Orden visual:

1. Foto pequena y circular, centrada.
2. CONTACTO.
3. APTITUDES CLAVE.
4. SOFTWARE.
5. EDUCACION.
6. IDIOMAS.

La educacion debe permanecer en el sidebar azul. No debe repetirse como seccion principal.

## Columna principal

Orden visual:

1. Nombre en mayusculas.
2. Titulos profesionales.
3. Linea de contacto y palabras clave.
4. PERFIL PROFESIONAL.
5. EXPERIENCIA PROFESIONAL.
6. FORMACION COMPLEMENTARIA, LOGROS e INTERESES cuando existan.

## Tipografia y ATS

- Texto real con `Paragraph`, nunca texto convertido en imagen.
- Helvetica o equivalente PDF estandar para facilitar extraccion ATS.
- Cuerpo compacto, justificado en los parrafos largos.
- No usar viñetas Unicode que puedan extraerse mal; usar guion ASCII (`-`).
- Las lineas son decorativas y no deben contener informacion.

## Dinamismo

- Gemini analiza la oferta y prioriza habilidades y experiencias que existan en `config/perfil_maestro.json`.
- Gemini no puede crear cargos, fechas, empresas, tecnologias ni metricas.
- La plantilla, colores, posiciones y jerarquia permanecen fijos; solo cambia el contenido adaptado.
- Si Gemini no responde, se usa el matching local y el PDF se genera igualmente.

## Archivos necesarios

- `.env`: clave de Gemini.
- `config/perfil_maestro.json`: fuente factual.
- `ofertas/*.docx`: entradas dinamicas.
- `CVS/CV_Anderson_Sarmiento_Modelo.pdf`: referencia visual.
- `foto.jpeg`: fotografia usada en el CV.
- `src/`: motor, extraccion, matching, Gemini, validacion y render.
- `tests/`: pruebas automaticas.
- `output/pdf/`: salida generada, puede limpiarse y regenerarse.

Los directorios `__pycache__/` y `.pytest_cache/` son temporales y no forman parte del proyecto.
