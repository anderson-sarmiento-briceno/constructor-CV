ññ# CONTEXTO DEL PROYECTO — CV DINÁMICO PERSONALIZADO POR OFERTA

## 1. Propósito del proyecto

Construir una aplicación que genere automáticamente un **Currículum Vitae (CV) personalizado para cada oferta laboral**, partiendo de una fuente maestra de información profesional obtenida a partir de los CVs históricos del candidato.

El flujo principal será:

1. El usuario carga una oferta/propuesta de trabajo en formato **Word (.docx)**.
2. El sistema lee y extrae el contenido de la oferta.
3. Identifica:
   - cargo;
   - responsabilidades;
   - requisitos;
   - conocimientos técnicos;
   - herramientas y tecnologías;
   - años de experiencia solicitados;
   - palabras clave;
   - competencias blandas;
   - nivel de seniority;
   - requisitos académicos;
   - certificaciones o idiomas;
   - otros criterios relevantes.
4. El sistema toma los **CVs antiguos de referencia en formato Word (.docx)** almacenados en la carpeta `CVS/`.
5. Convierte esos CVs de Word a **Markdown (.md)** y a una estructura JSON limpia mediante librerías de Python (`python-docx` + post-procesamiento).
6. Compara los requisitos de la oferta contra el perfil profesional extraído de los CVs históricos.
7. Utiliza **Gemini únicamente** para:
   - interpretar semánticamente la oferta;
   - detectar coincidencias exactas, semánticas y parciales;
   - priorizar experiencias y logros relevantes;
   - reescribir el resumen profesional y los bullets de forma natural y orientada a la oferta;
   - seleccionar las palabras clave ATS más potentes.
8. Genera una versión personalizada del CV.
9. El CV final se exporta a **PDF profesional, visualmente atractivo y compatible con sistemas ATS**.
10. Debe conservarse una separación estricta entre:
    - información verdadera/fija del candidato;
    - información adaptable (redacción, orden, énfasis);
    - información que puede ser inferida de forma prudente;
    - información que nunca debe inventarse.

**Objetivo real del sistema:**  
Maximizar la probabilidad de que el CV **pase los filtros ATS** y genere una propuesta de entrevista, sin alterar nunca los hechos reales de la trayectoria del candidato.

---

# 2. Principio fundamental

## PERSONALIZAR ≠ INVENTAR

El sistema puede:

- cambiar el orden de las experiencias;
- cambiar el título profesional utilizado en el encabezado cuando sea compatible con el perfil real;
- adaptar el resumen profesional;
- seleccionar las experiencias más relevantes para la oferta;
- priorizar determinados proyectos y logros;
- reorganizar habilidades;
- seleccionar y resaltar palabras clave presentes en la oferta;
- adaptar la redacción de logros existentes (sin inventar métricas);
- resaltar herramientas que realmente domina;
- adaptar el nivel de detalle de cada experiencia;
- eliminar temporalmente información poco relevante para una oferta concreta;
- combinar conocimientos existentes para presentar una experiencia de forma más relevante.

El sistema **NO puede**:

- inventar empleos;
- inventar empresas;
- inventar títulos académicos;
- inventar certificaciones;
- inventar años de experiencia;
- inventar herramientas no conocidas por el candidato;
- inventar proyectos;
- inventar resultados;
- inventar porcentajes o métricas;
- inventar cargos desempeñados;
- afirmar que el candidato trabajó con una tecnología si la base maestra no lo demuestra;
- modificar fechas reales;
- modificar instituciones educativas;
- modificar nombres de empresas;
- modificar logros cuantitativos reales;
- crear experiencia profesional ficticia solamente porque la oferta la solicita.

Si una oferta exige algo que no aparece en la información maestra, debe marcarse como:

`NO EVIDENCIADO EN EL PERFIL MAESTRO`

Nunca rellenarlo con información inventada.

---

# 3. Fuente maestra de información

La carpeta principal de contexto será:

```text
CVS/
```

Esta carpeta contendrá:

- CVs históricos en formato Word (.docx);
- CVs actuales;
- versiones especializadas;
- fotografías;
- documentos complementarios;
- posiblemente certificados;
- otros documentos profesionales relevantes.

### Flujo de extracción obligatorio

1. Tomar los archivos `.docx` de `CVS/`.
2. Convertirlos a Markdown limpio y estructurado usando librerías de Python (`python-docx` + post-procesamiento).
3. Extraer de forma controlada:
   - datos personales;
   - formación académica;
   - experiencia profesional (empresa, cargo, fechas, responsabilidades, logros);
   - habilidades técnicas y blandas;
   - certificaciones;
   - idiomas;
   - proyectos.
4. Consolidar toda esa información en un **perfil maestro estructurado** (`config/perfil_maestro.json`).
5. Los archivos Markdown generados y el JSON se convierten en la **fuente de verdad operacional**.

Los CVs de Word originales se conservan como respaldo histórico, pero **nunca se copian literalmente** al CV final.

## Regla de prioridad

Cuando existan varias versiones del CV:

1. información explícita del perfil maestro;
2. información respaldada por documentos;
3. información común y consistente entre varias versiones;
4. información de versiones anteriores solamente si no contradice la información actual.

Si dos documentos presentan información contradictoria, el sistema debe:

- detectar la contradicción;
- no decidir silenciosamente;
- conservar la información más reciente solamente si está claramente identificada como vigente;
- idealmente registrar la contradicción para revisión.

---

# 4. Información profesional base conocida

## Nombre

Anderson Sarmiento

## Profesión

Ingeniero Eléctrico.

## Formación académica

Información que debe tratarse como **fija**, salvo actualización explícita:

- Ingeniería Eléctrica — Universidad Distrital Francisco José de Caldas — 2013.
- Especialización en Gerencia de Proyectos — Universidad del Bosque — 2015.

La formación académica **NO debe ser modificada** por el modelo de IA.

El sistema podrá cambiar:

- el orden visual;
- el nivel de detalle;
- la descripción complementaria;

pero no los datos esenciales (título, universidad, año).

El CV actualmente consultado también contiene una formación de Científico de Datos en curso en Platzi; debe conservarse únicamente si continúa vigente según la fuente maestra actualizada. El documento fuente la registra como “Científico de Datos (En curso)”.

---

# 5. Experiencia profesional

La trayectoria debe estructurarse conceptualmente en bloques claros.  
Las **empresas, cargos reales y fechas** deben permanecer siempre iguales.  
Solo se adapta el énfasis, el orden y la redacción.

## 5.1. Enel

Experiencia principal de trayectoria profesional.

La información disponible en uno de los CV de referencia registra:

- Enel Colombia.
- Experiencia asociada a infraestructura, automatización, proyectos eléctricos y análisis de datos.
- Actividades relacionadas con:
  - automatización de procesos;
  - mantenimiento eléctrico;
  - gestión de contratistas;
  - indicadores operacionales;
  - Power BI;
  - proyectos de redes MT/BT;
  - SCADA;
  - modelos predictivos;
  - análisis histórico de fallas.

La aplicación debe utilizar la información de los CVs de `CVS/` como fuente definitiva para fechas, cargo exacto, responsabilidades y logros.

NO asumir automáticamente que todos los proyectos de Enel aplican a cualquier oferta.  
La IA debe seleccionar solamente los elementos pertinentes.

## 5.2. Freelance / Consultoría

Bloque profesional independiente.

La fuente de referencia contiene experiencia como:

**Consultor Freelance - Automatización y Eficiencia Energética**

y registra actividades relacionadas con:

- automatización avanzada;
- Python;
- NLP;
- chatbots;
- IoT;
- monitoreo energético;
- automatización administrativa;
- reportes;
- eficiencia energética;
- ISO 50001;
- diseño de sistemas eléctricos;
- análisis y reducción de consumo energético.

La aplicación debe consultar la fuente maestra para obtener las fechas definitivas.

## 5.3. Ciencia de Datos / BI / IA — experiencia reciente

Existe una etapa profesional reciente asociada a:

- Business Intelligence;
- análisis de datos;
- Python;
- Power BI;
- Machine Learning;
- automatización;
- ingeniería de datos;
- desarrollo de soluciones inteligentes;
- análisis energético;
- movilidad eléctrica;
- modelos predictivos;
- construcción de indicadores;
- tratamiento y análisis de grandes volúmenes de información.

**Experiencia específica más reciente (fuente maestra actualizada):**

- **Científico de Datos** — Green Mobil (empresa de movilidad de buses eléctricos).
- **Período:** 20 de julio de 2025 – 15 de septiembre de 2025.
- **Actividades y logros reales:**
  - Desarrollé e implementé un modelo de **regresión lineal** para el cálculo de la energía consumida por los buses, orientado a la certificación **ISO 50001**.
  - Implementé procesos **ETL** para automatizar, almacenar en **PostgreSQL** y visualizar en **Power BI** diferentes procesos internos.
  - Fuentes de datos integradas: API de operación de los buses, sistemas contables (Siesa), Excel y otras fuentes.
  - Todo el desarrollo realizado con **Python**.

Esta experiencia reciente debe considerarse especialmente importante para ofertas de:

- Data Scientist;
- Data Analyst;
- BI Analyst;
- BI Developer;
- Machine Learning;
- AI;
- Data Engineer;
- Analytics;
- Energy Analytics;
- movilidad eléctrica;
- optimización;
- automatización basada en datos;
- ISO 50001 / gestión energética.

La duración exacta de esta etapa debe tomarse de la fuente maestra actualizada y no debe ser inventada.

---

# 6. Capacidades técnicas maestras

La base maestra puede contener, entre otras:

### Ingeniería eléctrica
- Sistemas eléctricos.
- Redes MT/BT.
- Cálculos eléctricos.
- Eficiencia energética.
- Gestión energética.
- Mantenimiento eléctrico.
- Protección eléctrica.
- RETIE.
- CREG.
- Infraestructura energética.

### Datos y Business Intelligence
- Python.
- Pandas.
- Scikit-learn.
- Power BI.
- SQL.
- PostgreSQL.
- ETL.
- Data Warehouse.
- Análisis exploratorio.
- Visualización de datos.
- KPIs.
- Modelos predictivos.
- Machine Learning.
- Regresión lineal.
- Integración de APIs.
- Sistemas contables (Siesa).

### Automatización
- Automatización de procesos.
- RPA.
- Python.
- Chatbots.
- NLP.
- IoT.
- Integración de datos.
- Automatización de reportes.
- ETL automatizado.

### Gestión
- Gestión de proyectos.
- Coordinación multidisciplinaria.
- Gestión de contratistas.
- Seguimiento de indicadores.
- Optimización de procesos.

### Energía
- ISO 50001.
- Indicadores energéticos.
- Líneas base energéticas.
- Eficiencia energética.
- Análisis de consumo.
- Optimización energética.
- Cálculo de consumo energético en flotas de buses eléctricos.
- Movilidad eléctrica.

La lista anterior es una guía. La aplicación debe considerar como fuente definitiva los documentos existentes en `CVS/`.

---

# 7. Motor de adaptación (flujo técnico real)

## Objetivo

La adaptación debe funcionar como un problema de **matching inteligente entre oferta y perfil profesional real**, orientado siempre a maximizar la probabilidad de pasar filtros ATS y generar una entrevista.

Conceptualmente:

```text
CVs HISTÓRICOS (.docx)
       ↓
Conversión a Markdown + JSON (Python + python-docx)
       ↓
PERFIL MAESTRO ESTRUCTURADO
       ↓
OFERTA LABORAL (.docx)
       ↓
Extracción de requisitos (Python)
       ↓
Gemini (solo para análisis semántico y redacción adaptada)
       ↓
Clasificación de coincidencias + priorización de contenido
       ↓
Validación anti-alucinación (Python)
       ↓
Generación del CV adaptado
       ↓
Renderizado HTML/CSS → PDF profesional + ATS-friendly
```

**Regla de oro:**  
Gemini solo ayuda a interpretar, priorizar y redactar.  
La verdad factual siempre sale del perfil maestro.

---

# 8. Clasificación de requisitos

Cada requisito detectado en la oferta debe clasificarse en una de estas categorías:

### MATCH_EXACTO
La habilidad o experiencia aparece claramente en el perfil.

### MATCH_SEMANTICO
No existe exactamente la misma palabra, pero existe experiencia equivalente demostrable.

### MATCH_PARCIAL
Existe una relación, pero no suficiente para afirmar equivalencia total.

### NO_EVIDENCIADO
No existe evidencia suficiente en el perfil.

### REQUISITO_CRITICO_NO_CUBIERTO
El requisito parece indispensable para el cargo y no existe evidencia suficiente.  
Esto no significa que el CV deba inventar información. Debe servir para alertar al usuario.

---

# 9. Uso de Gemini (restricción clara)

Se utilizará Gemini **únicamente** para tareas de lenguaje y adaptación semántica:

- interpretar ofertas laborales;
- extraer y normalizar requisitos;
- detectar sinónimos y tecnologías equivalentes;
- identificar palabras clave ATS potentes;
- clasificar responsabilidades;
- determinar qué experiencias del candidato son más relevantes para la oferta;
- redactar un resumen profesional adaptado;
- reorganizar y reescribir bullets de forma natural;
- sugerir qué logros reales deben destacarse;
- generar una matriz oferta vs. perfil.

### Gemini NO debe ser la fuente de verdad

Gemini no puede decidir libremente qué experiencia tiene el candidato.  
No puede inventar fechas, empresas, títulos ni métricas.

Arquitectura recomendada:

```text
PERFIL MAESTRO (fuente de verdad)
      ↓
Oferta laboral
      ↓
Gemini (análisis + propuesta de adaptación)
      ↓
Validador de hechos (Python)
      ↓
GENERADOR DEL CV
```

La IA propone.  
El sistema valida.  
El sistema genera.

---

# 10. Arquitectura recomendada

Inicialmente desarrollar todo de forma local.

Propuesta:

```text
cv-dinamico/
│
├── CVS/                          # CVs históricos en Word + foto + documentos
│   ├── cv_*.docx
│   ├── foto/
│   └── documentos/
│
├── ofertas/
│   └── oferta_*.docx
│
├── output/
│   ├── pdf/
│   ├── markdown/
│   ├── json/
│   └── reportes/
│
├── config/
│   └── perfil_maestro.json       # Fuente de verdad operacional
│
├── templates/
│   └── cv_template.html          # Plantilla profesional ATS-friendly
│
├── src/
│   ├── extraction/               # Lectura de .docx → Markdown/JSON
│   ├── matching/                 # Comparación oferta vs perfil
│   ├── llm/                      # Llamadas controladas a Gemini
│   ├── validation/               # Anti-alucinación
│   ├── rendering/                # HTML → PDF
│   └── utils/
│
├── tests/
├── .env
├── requirements.txt
└── README.md
```

---

# 11. Perfil maestro estructurado

No depender exclusivamente de PDFs ni de Word para construir el CV final.

Debe existir un archivo estructurado:

```text
config/perfil_maestro.json
```

Este archivo debe almacenar:

```json
{
  "datos_personales": {},
  "perfil_profesional": {},
  "formacion": [],
  "experiencia": [],
  "habilidades": [],
  "certificaciones": [],
  "idiomas": [],
  "logros": [],
  "proyectos": []
}
```

El JSON se convierte en la **fuente de verdad operacional**.  
Los CVs de `CVS/` sirven como documentos de respaldo y contexto.

---

# 12. Datos que deben ser fijos (nunca modificar)

Los siguientes campos **NO deben ser modificados automáticamente**:

- nombre;
- teléfono;
- correo;
- LinkedIn;
- ciudad;
- títulos académicos;
- universidades;
- años de graduación;
- empresas;
- fechas reales de empleo;
- cargos reales;
- certificaciones;
- idiomas;
- fotografías;
- porcentajes de logros;
- métricas reales;
- proyectos que no estén soportados por la base maestra.

La IA solamente puede trabajar sobre la **presentación** de estos datos.

---

# 13. Datos que sí pueden adaptarse

### Perfil profesional / Resumen
Debe ser dinámico y orientado a la oferta.

Ejemplos de énfasis:

- **Data Scientist** → Python, Machine Learning, modelos predictivos, ETL, Power BI, experiencia Green Mobil, ISO 50001, movilidad eléctrica.
- **BI / Data Analyst** → Power BI, SQL, PostgreSQL, Python, ETL, KPIs, visualización, automatización, integración de APIs y Siesa.
- **Ingeniero Eléctrico / Project Manager** → Ingeniería Eléctrica, Gerencia de Proyectos, Enel, MT/BT, gestión de contratistas, eficiencia energética.
- **Energía / ISO 50001** → eficiencia energética, ISO 50001, análisis de consumo, Green Mobil, flotas eléctricas.

### Experiencia
- Cambiar orden de aparición.
- Ajustar nivel de detalle.
- Reescribir bullets enfocados en impacto y tecnologías relevantes.
- Destacar logros reales que coincidan con lo que pide la oferta.

---

# 14. Adaptación de experiencia

No se debe mostrar necesariamente toda la experiencia con el mismo nivel de detalle.

Ejemplo para oferta **Data Scientist**:

```text
GREEN MOBIL (más reciente)
- modelo de regresión lineal para consumo energético de buses eléctricos
- certificación ISO 50001
- ETL con Python → PostgreSQL → Power BI
- integración de API de operación de buses, Siesa y Excel

ENEL
- modelos predictivos
- análisis de datos históricos
- automatización
- Power BI

FREELANCE
- Python, automatización, chatbots, IoT, análisis energético
```

La trayectoria no cambia. Solo cambia el enfoque y la prioridad visual.

---

# 15. Palabras clave ATS

El sistema debe extraer las palabras clave de la oferta y comprobar cuáles existen en el perfil.

Debe priorizar palabras clave relacionadas con:

- cargo;
- tecnologías;
- herramientas;
- metodologías;
- certificaciones;
- sectores;
- funciones;
- competencias técnicas.

Nunca añadir una tecnología o habilidad solo porque aparece en la oferta.

---

# 16. Diseño visual del PDF

El CV debe verse profesional, moderno y estético, pero el diseño debe estar **subordinado** a la legibilidad ATS y a la probabilidad de pasar filtros.

## Principios

- máximo 2 páginas cuando sea posible;
- tipografía profesional y limpia;
- excelente jerarquía visual;
- espacios bien utilizados;
- títulos claros;
- fechas fácilmente identificables;
- bullets cortos y orientados a impacto;
- suficiente espacio en blanco;
- diseño sobrio y elegante;
- buena lectura en pantalla y en impresión;
- PDF con texto seleccionable (nunca imagen completa);
- evitar convertir todo el CV en una imagen.

---

# 17. Compatibilidad ATS (prioridad alta)

Evitar absolutamente:

- tablas complejas;
- columnas excesivas;
- texto dentro de imágenes;
- barras de nivel de habilidades;
- iconos como sustitutos de texto;
- información crítica únicamente en encabezados gráficos;
- gráficos e infografías;
- porcentajes visuales;
- texto oculto;
- fuentes extrañas o no estándar.

Preferir:

```text
HTML + CSS limpio → PDF
```

El PDF final debe poder ser leído perfectamente por:

- lectores humanos;
- sistemas ATS;
- extracción de texto;
- modelos de lenguaje.

**Meta:** que el CV se vea diseñado por un profesional de selección y, al mismo tiempo, sea 100 % legible por cualquier ATS.

---

# 18. Fotografía

La fotografía puede existir en la carpeta `CVS/`, pero debe ser configurable:

```text
INCLUIR_FOTO = true | false
```

No asumir que todas las ofertas requieren fotografía.  
La fotografía nunca debe contener información necesaria para comprender el CV.

---

# 19. Nombre de archivos generados

Formato recomendado:

```text
CV_Anderson_Sarmiento_<CARGO>_<EMPRESA>.pdf
```

También generar opcionalmente:

```text
CV_Anderson_Sarmiento_<CARGO>_<EMPRESA>.json
```

con el resultado de la adaptación y el reporte técnico.

---

# 20. Reporte de adaptación

Además del PDF, el sistema debe generar un pequeño reporte técnico interno:

```text
CARGO DETECTADO:
...

PALABRAS CLAVE:
...

COINCIDENCIAS:
...

NO EVIDENCIADO:
...

EXPERIENCIA PRIORIZADA:
1. ...
2. ...

ESTADO:
CV generado
```

Este reporte no forma parte del PDF enviado al empleador.

---

# 21. Control anti-alucinación

Antes de generar el PDF debe existir una validación estricta:

```text
Texto generado por Gemini
        ↓
Extraer afirmaciones factuales
        ↓
Comparar contra perfil maestro
        ↓
¿Existe evidencia?
       / \
     SI   NO
     ↓     ↓
 aprobar  rechazar / marcar
```

Toda afirmación factual debe poder rastrearse hasta el perfil maestro o los documentos fuente.

---

# 22. Versionado

Cada CV generado debe conservar:

- oferta original;
- fecha de generación;
- versión del perfil maestro;
- modelo Gemini utilizado;
- configuración utilizada;
- resultado del matching;
- PDF generado.

Esto permitirá auditoría y reproducibilidad.

---

# 23. Posible flujo de usuario

1. Cargar oferta Word.
2. Mostrar cargo y empresa detectados.
3. Mostrar coincidencias y requisitos no evidenciados.
4. Permitir revisar la adaptación (resumen, palabras clave, experiencia priorizada).
5. Generar CV.
6. Descargar PDF + (opcional) reporte JSON.

---

# 24. Stack tecnológico sugerido

### Backend
Python.

### Lectura y conversión de Word
- `python-docx`
- Procesamiento propio a Markdown limpio + JSON estructurado.

### Procesamiento
- Python
- Pandas
- Pydantic

### LLM
Gemini (API) **únicamente** para análisis semántico, matching y redacción adaptada.

### Generación PDF
HTML + CSS → PDF (herramienta que preserve texto seleccionable).

### Configuración
`.env` para API keys.  
Nunca guardar claves en el código.

---

# 25. Seguridad

Nunca subir a Git:

```text
.env
CVS/
output/
__pycache__/
```

Agregar estas rutas al `.gitignore`.

---

# 26. Regla de diseño del CV

El CV debe parecer diseñado por un profesional de selección y no generado automáticamente.

Debe evitar:
- exceso de colores;
- exceso de iconos;
- diseño de infografía;
- barras de habilidades;
- frases genéricas;
- párrafos largos;
- repetición de “responsable de…”.

Debe favorecer:
- resultados e impacto;
- tecnologías concretas;
- contexto claro;
- verbos de acción;
- cifras reales (solo las que existan);
- claridad y escaneabilidad.

---

# 27. Redacción de logros

Siempre que exista una métrica real, conservarla.  
Nunca crear nuevas cifras.

Ejemplo válido (si está respaldado):

```text
Implementé flujos de trabajo automatizados que redujeron tiempos de procesamiento en 30%.
```

---

# 28. Estrategia de adaptación

El algoritmo puede utilizar una puntuación interna para decidir qué contenido mostrar, pero:

**la puntuación NO debe aparecer como una valoración de la persona.**

Sirve exclusivamente para ordenar contenido y maximizar relevancia frente a la oferta.

---

# 29. Separación entre extracción y generación

No mezclar todo en una sola llamada al modelo.

Recomendación obligatoria:

```text
1. Convertir CVs Word → Markdown + JSON (Python)
2. Extraer y estructurar oferta (Python)
3. Comparar oferta vs perfil maestro
4. Llamar a Gemini solo para análisis semántico + redacción adaptada
5. Validar hechos (Python)
6. Renderizar PDF profesional + ATS-friendly
```

Esto facilita depuración, trazabilidad, control de errores y reducción de alucinaciones.

---

# 30. Resultado esperado

```text
CVs históricos Word
      ↓
Extracción a Markdown + Perfil Maestro
      ↓
Oferta Word
      ↓
Análisis + Adaptación (Gemini solo para lenguaje)
      ↓
Validación de hechos
      ↓
CV profesional personalizado
      ↓
PDF ATS-friendly + visualmente atractivo
```

Siempre manteniendo:

```text
VERACIDAD
+
TRAZABILIDAD
+
PERSONALIZACIÓN INTELIGENTE
+
DISEÑO PROFESIONAL
+
COMPATIBILIDAD ATS
+
ORIENTACIÓN A CONSEGUIR LA ENTREVISTA
```

---

# 31. Requisito importante para el desarrollo

Antes de escribir código de generación de PDF:

1. Revisar todos los archivos disponibles en `CVS/`.
2. Convertir los CVs Word a Markdown limpio.
3. Construir el perfil maestro JSON.
4. Identificar información duplicada y contradicciones.
5. Definir qué información es fija y qué es adaptable.
6. Definir estructura JSON definitiva.
7. Definir plantilla visual profesional y ATS-friendly.
8. Definir reglas de uso de Gemini (solo lenguaje y matching).
9. Crear casos de prueba con diferentes tipos de ofertas.
10. Solo después comenzar a programar el generador.

Primero construir la **fuente de verdad del candidato**.

---

# 32. Casos de prueba mínimos

El sistema debe probarse al menos con:

### Caso A — Data Scientist
Priorizar: Python, Machine Learning, análisis de datos, modelos predictivos, Green Mobil, Power BI, ETL, PostgreSQL, regresión lineal, ISO 50001, movilidad eléctrica.

### Caso B — BI / Data Analyst
Priorizar: Power BI, SQL, PostgreSQL, Python, KPIs, ETL, visualización, automatización, integración de APIs y Siesa.

### Caso C — Ingeniero Eléctrico
Priorizar: Ingeniería Eléctrica, Enel, MT/BT, mantenimiento, infraestructura, eficiencia energética, proyectos.

### Caso D — Gerencia de Proyectos
Priorizar: Especialización en Gerencia de Proyectos, gestión, coordinación, contratistas, proyectos eléctricos, seguimiento, indicadores.

### Caso E — Energía / ISO 50001
Priorizar: eficiencia energética, ISO 50001, análisis de consumo, Green Mobil, flotas de buses eléctricos, gestión energética.

El mismo candidato debe producir CVs diferentes en enfoque, pero **ninguno debe alterar los hechos reales de su trayectoria**.

---

# 33. Principio final para cualquier desarrollador o agente de IA

Este proyecto no consiste en fabricar un CV diferente para cada oferta.

Consiste en construir un:

> **Sistema de selección, priorización, adaptación y presentación de información profesional real.**

- La información del candidato es la fuente de verdad.
- La oferta determina qué información debe tener mayor visibilidad.
- Gemini ayuda a interpretar y redactar.
- El validador evita inventar.
- El generador produce el PDF.
- La plantilla garantiza diseño profesional y compatibilidad ATS.
- El proceso completo debe ser reproducible, auditable y orientado a **conseguir la entrevista**.

La flexibilidad es total en la presentación.  
La veracidad es absoluta en los hechos.
