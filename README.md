# MIRA · Entrega 3: Asistente con RAG y Servidor MCP Propio (CU-1)

Implementación completa del **Caso de Uso 1 (Asistente del Operador de Revisión)** para la plataforma **MIRA** (DPRIME SpA), desarrollado en el marco del *Taller de Desarrollo de Software Conducido por Agentes de IA* (Escuela de Ingeniería Informática, Universidad de Valparaíso).

**Autores:** Max Latuz Zepeda & Joaquín Aguilera Arellano

---

## 1. Propósito y Principios No Negociables (`PR-1` a `PR-7`)

El asistente apoya a los operadores de organizaciones cliente (`ORG-01` Seguros Cordillera Austral, `ORG-02` Clínica Bahía Serena y `ORG-03` Banco Mirador del Sur) al revisar casos derivados por MIRA, combinando tres pilares gobernados:

1. **Evidencia Documental Verificable (RAG):**
   - Indexación reproducible y separada de la consulta sobre **7 documentos (38 fragmentos)** de dos orígenes: los 6 documentos normativos del kit oficial más la Descripción del Proyecto (`DOC-MIRA v1.4`).
   - Búsqueda híbrida (**BM25 léxico + TF-IDF de n-gramas de caracteres**) con preservación íntegra de tablas Markdown y citas canónicas `[Código, §Sección, vVersión (Estado)]` (`PR-2`).
   - Control explícito de vigencia (`POL-DEC v2` vigente vs. `POL-DEC v1` derogada), exposición neutral de contradicciones entre fuentes vigentes (`POL-DEC v2 §2` umbral 85 vs. `MAN-REV v1 §1` umbral 80, `PR-4`) y abstención honesta ante consultas fuera del corpus (`PR-3`).
2. **Acceso Gobernado a Datos Vivos (Servidor MCP Propio):**
   - Consultas 100 % parametrizadas (`?`) sobre SQLite (`data/mira_cu1.db`) poblada desde `CU-1_datos.xlsx`, sin que el modelo escriba jamás SQL.
   - Expone las 3 primitivas del protocolo (**5 Tools**, **2 Resources** y **2 Prompts**) tanto vía API interna como por protocolo estándar **JSON-RPC 2.0 sobre `stdio`** (`--stdio`).
   - Imposición de reglas de negocio y seguridad en el servidor: aislamiento multi-organización (`PR-7`), detección y neutralización de *Prompt Injection* en evidencias (`E-007` en `C-014`), auditoría de cambios de umbral sin segunda firma de supervisor (`CU-001` en `C-012`), límite máximo de 2 solicitudes por operador (`PRO-ANT §4` en `C-016`) y confirmación humana explícita en dos pasos (`confirmado=True`, `PR-6`).
3. **Orquestador con Google Gemini Flash y Frontend Web en Español (Streamlit):**
   - Integración con **Google Gemini API** en la nube (`gemini-3.5-flash-lite` con rotación automática en cascada hacia `gemini-3.1-flash-lite`, `gemini-3.5-flash` y `gemini-3-flash-preview` ante límites de cuota gratuita, más respaldo determinista local si no hay red o llave configurada).
   - Interfaz web en español (`src/ui/app.py`) con selector de usuario conectado, indicadores visuales de estado, citas desplegables (`D1`), trazas MCP y declaración de datos enviados al modelo (`D4`), tarjeta/botón de confirmación humana (`D5`, `PR-6`) y simulación de caída de proveedor.

---

## 2. Estructura del Repositorio

```text
├── .env.example                       # Plantilla de variables de entorno para Google Gemini API
├── requirements.txt                   # Dependencias del proyecto
├── data/
│   ├── corpus/                        # 7 documentos Markdown del corpus (6 del kit + DOC-MIRA v1.4)
│   ├── raw/                           # Archivo Excel oficial del kit (CU-1_datos.xlsx)
│   ├── golden_set.json                # Golden Set de 22 preguntas versionado previo al pipeline
│   ├── rag_index.json                 # Índice RAG generado con metadatos por fragmento (38 chunks)
│   └── mira_cu1.db                    # Base de datos SQLite generada desde CU-1_datos.xlsx
└── src/
    ├── db/
    │   └── init_db.py                 # Cargador reproducible de las 7 hojas del Excel a SQLite
    ├── rag/
    │   ├── indexer.py                 # Indexación por sección Markdown separada de la consulta
    │   ├── retriever.py               # Búsqueda híbrida (BM25 + TF-IDF), citas, vigencia y conflictos
    │   └── experiment_chunking.py     # Experimento comparativo de 3 estrategias de fragmentación
    ├── mcp_server/
    │   ├── server.py                  # Servidor MCP propio (Tools, Resources, Prompts y --stdio)
    │   └── external_client_demo.py    # Cliente MCP externo sobre JSON-RPC 2.0 stdio (Demo D7)
    ├── api/
    │   ├── agent.py                   # Orquestador agéntico (Google Gemini + RAG + MCP + Guardrails)
    │   ├── main.py                    # Servidor HTTP/FastAPI (/chat, /mcp/tools, /mcp/call, /health)
    │   └── chat_cli.py                # Cliente interactivo de consola multi-usuario
    ├── ui/
    │   └── app.py                     # Interfaz Web en Español en Streamlit (Criterio C5, D1 a D8)
    └── eval/
        └── run_evaluation.py          # Evaluación empírica sobre las 22 preguntas del Golden Set
```

---

## 3. Configuración e Instalación

### 3.1. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3.2. Configurar Google Gemini API (`.env`)
El proyecto incluye soporte nativo para **Google Gemini API** (capa gratuita de Google AI Studio) y un sintetizador determinista de respaldo si se ejecuta sin conexión. Para activar Gemini en la nube:
1. Copia el archivo `.env.example` a `.env` en la raíz del proyecto:
   ```bash
   cp .env.example .env
   ```
2. Edita `.env` y coloca tu clave gratuita obtenida en [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey):
   ```env
   GEMINI_API_KEY=TU_API_KEY_AQUI
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

---

## 4. Ejecución y Verificación Paso a Paso

```bash
# 1. Inicializar la base de datos SQLite desde el Excel oficial del kit
python -m src.db.init_db

# 2. Construir el índice RAG (38 fragmentos) y correr el experimento comparativo de fragmentación
python -m src.rag.indexer
python -m src.rag.experiment_chunking

# 3. Verificar las herramientas, recursos, prompts y reglas de negocio del Servidor MCP
python -m src.mcp_server.server

# 4. Demostración D7: Conectar un cliente MCP externo al servidor vía JSON-RPC 2.0 sobre stdio
python -m src.mcp_server.external_client_demo

# 5. Ejecutar la evaluación oficial sobre las 22 preguntas del Golden Set (Recall@k, Fidelidad, Abstención)
python -m src.eval.run_evaluation

# 6. Iniciar la Interfaz Web en Español (Streamlit) en http://localhost:8501
python -m streamlit run src/ui/app.py

# (Opcional) Levantar el servidor API Backend FastAPI en http://127.0.0.1:8000
python -m src.api.main
```
