# MIRA · Entrega 3: Asistente con RAG y Servidor MCP (CU-1)

Implementación completa del **Caso de Uso 1 (Asistente del Operador de Revisión)** para la plataforma **MIRA** (DPRIME SpA), desarrollado en el marco del *Taller de Desarrollo de Software Conducido por Agentes de IA* (Universidad de Valparaíso).

---

## 1. Propósito y Principios No Negociables (`PR-1` a `PR-7`)
El asistente apoya a los operadores de organizaciones cliente que revisan casos derivados por MIRA, combinando:
1. **Evidencia Documental (RAG):** Respuestas respaldadas estrictamente por fragmentos del corpus con cita verificable (`[Código, §Sección, vVersión (Estado)]`), detección de normas derogadas (`POL-DEC v1` vs `v2`), presentación neutral de conflictos entre normas vigentes (`POL-DEC v2 §2` umbral 85 vs `MAN-REV v1 §1` umbral 80) y abstención explícita ante falta de evidencia (`PR-3`).
2. **Acceso Gobernado a Datos Vivos (Servidor MCP):** Consultas 100 % parametrizadas sobre base de datos SQLite cargada desde el kit oficial (`CU-1_datos.xlsx`), respetando aislamiento por organización/rol (`PR-7`), detección de ataques de *Prompt Injection* en evidencias (`E-007` en `C-014`), auditoría de cambios de umbral sin doble aprobación (`CU-001` en `C-012`), validación de reglas de negocio en servidor (`PRO-ANT §4` en `C-016`) y confirmación humana explícita para acciones con efecto (`PR-6`).

---

## 2. Estructura del Repositorio

```text
├── data/
│   ├── corpus/                    # 6 documentos Markdown oficiales del corpus (CU-1)
│   ├── raw/                       # Archivo Excel oficial (CU-1_datos.xlsx)
│   └── golden_set.json            # Golden set de 22 preguntas versionado previo al pipeline
├── src/
│   ├── db/
│   │   └── init_db.py             # Cargador reproducible de Excel a SQLite (data/mira_cu1.db)
│   ├── rag/
│   │   ├── indexer.py             # Indexación y metadatos separados de la consulta
│   │   ├── retriever.py           # Búsqueda híbrida (BM25 + TF-IDF n-gramas), citas y vigencia
│   │   └── experiment_chunking.py # Experimento comparativo de fragmentación (Criterio C3)
│   ├── mcp_server/
│   │   └── server.py              # Servidor MCP propio (Tools, Resources, Prompts y Guardrails)
│   ├── api/
│   │   ├── agent.py               # Orquestador agéntico (RAG + MCP) y declaración de datos
│   │   └── main.py                # Servidor HTTP/FastAPI para conexión con el Frontend
│   ├── ui/
│   │   └── app.py                 # Interfaz Web en Streamlit para el operador (Sección 6.1, Criterio C5)
│   └── eval/
│       └── run_evaluation.py      # Evaluación empírica sobre las 22 preguntas del Golden Set
└── requirements.txt
```

---

## 3. Ejecución y Verificación Rápida

```bash
# 1. Inicializar la base de datos SQLite desde el Excel del kit
python src/db/init_db.py

# 2. Construir el índice RAG y ejecutar el experimento comparativo de fragmentación
python src/rag/indexer.py
python -m src.rag.experiment_chunking

# 3. Verificar las herramientas y reglas del Servidor MCP
python -m src.mcp_server.server

# 4. Probar el orquestador combinando RAG + MCP (C-012, C-014, C-016)
python -m src.api.agent

# 5. Ejecutar la evaluación completa sobre las 22 preguntas del Golden Set
python -m src.eval.run_evaluation

# 6. Levantar el servidor API Backend en http://127.0.0.1:8000
python -m src.api.main

# 7. Iniciar la Interfaz Web en Español (Frontend de Operador en Streamlit)
streamlit run src/ui/app.py
```
