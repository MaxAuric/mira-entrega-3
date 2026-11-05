# MIRA · Entrega 3: Asistente con RAG y Servidor MCP (CU-1)

Implementación del **Caso de Uso 1 (Asistente del Operador de Revisión)** para la plataforma **MIRA** (DPRIME SpA), desarrollado en el marco del *Taller de Desarrollo de Software Conducido por Agentes de IA* (Universidad de Valparaíso).

---

## 1. Propósito y Principios No Negociables
El asistente apoya a los operadores de organizaciones cliente que revisan casos derivados por MIRA, combinando:
1. **Evidencia Documental (RAG):** Respuestas respaldadas estrictamente por fragmentos del corpus con cita verificable (`[Código, Sección, Versión]`), detección de normas derogadas (`POL-DEC v1` vs `v2`), presentación neutral de conflictos entre normas vigentes (`POL-DEC v2 §2` vs `MAN-REV v1 §1`) y abstención explícita ante falta de evidencia.
2. **Acceso Gobernado a Datos Vivos (Servidor MCP):** Consultas parametrizadas sobre base de datos SQLite cargada desde el kit oficial, respetando aislamiento por organización/rol (`PR-7`), validación de reglas de negocio en servidor (`PRO-ANT §4`) y confirmación humana explícita para acciones con efecto (`PR-6`).

---

## 2. Estructura del Repositorio

```text
├── data/
│   ├── corpus/             # Documentos Markdown del corpus oficial (CU-1)
│   ├── raw/                # Archivo Excel original (CU-1_datos.xlsx)
│   └── golden_set.json     # Golden set de 22 preguntas versionado previo al pipeline
├── src/
│   ├── db/
│   │   └── init_db.py      # Cargador reproducible de Excel a SQLite (data/mira_cu1.db)
│   ├── rag/                # Indexación, recuperación y experimento de fragmentación
│   ├── mcp_server/         # Servidor MCP con herramientas parametrizadas y guardrails
│   ├── api/                # Orquestador del asistente y backend FastAPI
│   └── eval/               # Evaluación automatizada sobre el Golden Set
└── requirements.txt
```

---

## 3. Inicialización Rápida de Datos (Bloque 1)

```bash
pip install -r requirements.txt
python src/db/init_db.py
```

