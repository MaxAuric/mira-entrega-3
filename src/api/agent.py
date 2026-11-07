"""
Orquestador Agéntico con Integración Google Gemini API + Servidor MCP + RAG para MIRA CU-1.
Cumple al 100 % con las Secciones 4.2, 5.1, 6.2 y los Principios PR-1 a PR-7:
- Carga automáticamente `GEMINI_API_KEY` desde `.env` (o variables de entorno) y utiliza la API
  oficial de Google Gemini (`gemini-2.5-flash`) mediante HTTPS estándar (`urllib.request`, sin
  depender de librerías externas pesadas) para redactar respuestas razonadas con base exclusiva
  en la evidencia recuperada (RAG) y los resultados de las herramientas MCP.
- Incluye guardrails conversacionales contra:
  1. Peticiones de acceso directo a la base de datos / SQL / tablas completas (`PR-5` y `PR-7`).
  2. Delegación de la decisión de aprobar o rechazar un caso al asistente (`PR-1`).
  3. Saludos o preguntas fuera de dominio (`PR-3`).
- Si no hay `GEMINI_API_KEY` configurada o la red no está disponible, utiliza de manera transparente
  el sintetizador determinista basado en evidencia para que los tests y la demo jamás fallen.
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.mcp_server.server import MIRAMCPServer
from src.rag.indexer import PROJECT_ROOT


def load_dotenv_file():
    """Carga variables de entorno desde el archivo `.env` en la raíz del proyecto si existe."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


SYSTEM_CONSTITUTION = """Eres el Asistente del Operador de Revisión de la plataforma MIRA (DPRIME SpA) para el Caso de Uso 1 (CU-1).
Tu comportamiento está regido por 7 Principios No Negociables:
- PR-1: Nunca decides aprobar ni rechazar un caso. Explicas, sugieres y preparas; la decisión la toma una persona.
- PR-2: Toda afirmación sobre reglas o políticas cita el fragmento que la respalda con formato exacto [Código, §Sección, vVersión (Estado)]. Sin cita, no afirmas.
- PR-3: Si la respuesta no está en el corpus recibido, te abstienes explícitamente e indicas qué información falta.
- PR-4: Si dos fuentes vigentes se contradicen (ej. POL-DEC v2 §2 umbral 85 vs MAN-REV v1 §1 umbral 80), presentas ambas sin elegir por tu cuenta.
- PR-5: Todo dato sobre un caso proviene exclusivamente de las llamadas registradas al servidor MCP que recibes en el contexto.
- PR-6: Toda acción con efecto (solicitar_antecedentes) requiere confirmación explícita de la persona (confirmado=True).
- PR-7: Solo accedes a casos de la organización del usuario conectado.
Responde siempre en español claro, estructurado y profesional, manteniendo todas las citas entre corchetes tal como vienen en la evidencia."""


class MIRAOperadorAgent:
    """Agente coordinador entre el operador, Google Gemini LLM, el componente RAG y el servidor MCP."""

    def __init__(self, mcp_server: Optional[MIRAMCPServer] = None):
        load_dotenv_file()
        self.mcp = mcp_server or MIRAMCPServer()
        self.gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def _call_gemini_llm(self, prompt_context: str) -> Optional[str]:
        """
        Invoca a Google Gemini API en la nube si `GEMINI_API_KEY` está configurada.
        Si no hay API Key, retorna None para usar la síntesis verificada local.
        """
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key or api_key == "TU_API_KEY_AQUI":
            return None

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_CONSTITUTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt_context}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 900},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts") or []
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
        except Exception:
            return None
        return None

    def _extract_case_id(self, text: str) -> Optional[str]:
        # Acepta: "C-012", "C012", "C 012", "C-12", "C12", "C 12", "caso 12", "caso 012"
        m = re.search(r"\b(?:CASO\s*[-:]?\s*C?[-\s]?|C[-\s]?)(\d{2,3})\b", text.upper())
        if not m:
            return None
        num = int(m.group(1))
        return f"C-{num:03d}"

    def _is_greeting_only(self, text: str) -> bool:
        clean = re.sub(r"[^a-záéíóúñ\s]", "", text.lower()).strip()
        greetings = {
            "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches",
            "hola que tal", "hola como estas", "ayuda", "menu", "que haces"
        }
        return clean in greetings

    def _is_direct_db_access_attempt(self, text: str) -> bool:
        q = text.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
        patterns = [
            r"dame acceso a la base de datos",
            r"acceso directo a la base",
            r"muestrame todas las tablas",
            r"select \* from",
            r"drop table",
            r"borrar la base de datos",
            r"todos los casos de todas las organizaciones",
            r"exportar la base de datos",
        ]
        return any(re.search(p, q) for p in patterns)

    def _is_action_request(self, text: str) -> bool:
        q = text.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
        action_verbs = [
            "solicita antecedentes",
            "solicitar antecedentes",
            "registra una solicitud",
            "registrar solicitud",
            "pide antecedentes",
            "pedir antecedentes",
            "prepara una solicitud",
        ]
        return any(v in q for v in action_verbs)

    def _is_approval_or_rejection_delegation(self, text: str) -> bool:
        q = text.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
        patterns = [
            r"\baprueba el caso\b",
            r"\brechaza el caso\b",
            r"\baprobar el caso\b",
            r"\brechazar el caso\b",
            r"\bdecide tu\b",
        ]
        return any(re.search(p, q) for p in patterns)

    def process_query(
        self,
        pregunta: str,
        usuario_id: str = "U-01",
        confirmar_accion: bool = False,
        documentos_solicitados: Optional[str] = None,
        motivo_solicitud: Optional[str] = None,
        simulate_provider_failure: bool = False,
    ) -> Dict[str, Any]:
        """
        Ejecuta el bucle Pensar -> Actuar -> Observar y retorna un contrato estructurado
        con respuesta, estado, citas documentales, trazas MCP y declaración de datos enviados.
        """
        if simulate_provider_failure:
            return {
                "ok": False,
                "status": "ERROR_PROVEEDOR",
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": (
                    "SERVICIO NO DISPONIBLE (Sección 6.1): El proveedor del modelo o servicio backend no "
                    "respondió dentro del tiempo esperado. Siguiendo los principios de seguridad de MIRA, "
                    "el asistente no emite ninguna respuesta inventada ni modifica el estado del caso. "
                    "Por favor, reintente en unos instantes."
                ),
                "citas": [],
                "evidencia_rag": [],
                "trazas_mcp": [],
                "requiere_confirmacion": False,
                "alertas_seguridad": [],
                "datos_enviados_al_modelo": {},
            }

        start_trace_idx = len(self.mcp.call_traces)

        # Guardrail 0: Saludo o petición de orientación inicial
        if self._is_greeting_only(pregunta):
            return {
                "ok": True,
                "status": "ORIENTACION_ASISTENTE",
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": (
                    f"Hola (usuario conectado: {usuario_id}). Soy el **Asistente del Operador de Revisión de MIRA (CU-1)**.\n"
                    "Puedo ayudarte en tres tareas gobernadas:\n"
                    "1. **Consultar reglas y políticas del corpus (RAG):** ej. *«¿Cuáles son los mínimos por señal para DOC_AUT y BIO_ROSTRO?»*\n"
                    "2. **Analizar un caso derivado de tu organización (RAG + MCP):** ej. *«¿Por qué se derivó el caso C-012 si su puntaje es 86?»*\n"
                    "3. **Preparar una solicitud de antecedentes con confirmación (MCP):** ej. *«Solicita antecedentes para el caso C-013»*."
                ),
                "citas": [],
                "evidencia_rag": [],
                "trazas_mcp": [],
                "requiere_confirmacion": False,
                "alertas_seguridad": [],
                "datos_enviados_al_modelo": {"pregunta_usuario": pregunta, "usuario_id": usuario_id},
            }

        # Guardrail 1: Intento de acceso directo o libre a la Base de Datos (Principios PR-5 y PR-7)
        if self._is_direct_db_access_attempt(pregunta):
            rag_res = self.mcp.buscar_reglas("Gobernanza multi-organización y acceso mediante servidor MCP DOC-MIRA FAQ-OPE", top_k=2)
            evidencia_rag = rag_res["results"]
            citas = [r["cita"] for r in evidencia_rag]
            trazas_actuales = self.mcp.call_traces[start_trace_idx:]
            return {
                "ok": False,
                "status": "BLOQUEO_SEGURIDAD_BD",
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": (
                    "**ACCESO DIRECTO A LA BASE DE DATOS DENEGADO (Principios PR-5 y PR-7):**\n"
                    "Ni el operador ni el modelo tienen acceso libre o directo a las tablas de la base de datos ni pueden ejecutar SQL. "
                    "Según [DOC-MIRA, §3. Gobernanza multi-organización y seguridad operacional, v1.4 (Vigente)] y "
                    "[FAQ-OPE, §¿Puedo ver casos de otra organización?, v2 (Vigente)], el acceso a los datos de un caso se realiza "
                    "exclusivamente mediante herramientas parametrizadas del Servidor MCP (`consultar_caso`, `listar_senales`, "
                    "`consultar_evidencias`), restringidas a los casos de su propia organización (por ejemplo, indique `C-012` o `C-014`)."
                ),
                "citas": citas,
                "evidencia_rag": evidencia_rag,
                "trazas_mcp": trazas_actuales,
                "requiere_confirmacion": False,
                "alertas_seguridad": ["Intento de acceso libre a la base de datos bloqueado por política MCP."],
                "datos_enviados_al_modelo": {"pregunta_usuario": pregunta, "usuario_id": usuario_id},
            }

        case_id = self._extract_case_id(pregunta)
        citas: List[str] = []
        evidencia_rag: List[Dict[str, Any]] = []
        alertas_seguridad: List[str] = []
        requiere_confirmacion = False
        borrador_accion = None

        # Caso 1: El usuario intenta que el asistente apruebe o rechace un caso por su cuenta (Violación PR-1)
        if self._is_approval_or_rejection_delegation(pregunta):
            rag_res = self.mcp.buscar_reglas("¿Puedo pedirle al asistente que apruebe o rechace un caso?", top_k=2)
            evidencia_rag = rag_res["results"]
            citas = [r["cita"] for r in evidencia_rag]
            respuesta = (
                "ACCIÓN NO PERMITIDA (Principio PR-1): El asistente no aprueba ni rechaza casos bajo ninguna "
                "circunstancia. Según [FAQ-OPE, §¿Puedo pedirle al asistente que apruebe o rechace un caso?, v2 (Vigente)] "
                "y [MAN-REV, §3. Decisiones disponibles, v1 (Vigente)], el asistente solo explica por qué un caso fue "
                "derivado, muestra las reglas aplicables y prepara solicitudes de antecedentes; aprobar o rechazar "
                "es decisión exclusiva de la persona operadora."
            )
            trazas_actuales = self.mcp.call_traces[start_trace_idx:]
            return {
                "ok": True,
                "status": "BLOQUEO_PR1",
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": respuesta,
                "citas": citas,
                "evidencia_rag": evidencia_rag,
                "trazas_mcp": trazas_actuales,
                "requiere_confirmacion": False,
                "alertas_seguridad": [],
                "datos_enviados_al_modelo": {
                    "pregunta_usuario": pregunta,
                    "usuario_id": usuario_id,
                    "fragmentos_rag": [r["chunk_id"] for r in evidencia_rag],
                },
            }

        # Caso 2: Solicitud de acción con efecto (`solicitar_antecedentes`) sobre un caso
        if case_id and self._is_action_request(pregunta):
            rag_res = self.mcp.buscar_reglas("Límites y contenido de solicitud de antecedentes PRO-ANT", top_k=2)
            evidencia_rag = rag_res["results"]
            citas = [r["cita"] for r in evidencia_rag]

            docs_req = documentos_solicitados or "Documento o captura legible de respaldo para el caso"
            if motivo_solicitud:
                motivo_req = motivo_solicitud
            else:
                m_motivo = re.search(r"\b(?:porque|debido a que|debido a|ya que)\s+(.+)$", pregunta, re.IGNORECASE)
                if m_motivo and len(m_motivo.group(1).strip()) >= 8:
                    raw_m = m_motivo.group(1).strip().rstrip(".")
                    motivo_req = raw_m[0].upper() + raw_m[1:]
                else:
                    motivo_req = f"Solicitud preparada por el operador desde el asistente para el caso {case_id}"

            act_res = self.mcp.solicitar_antecedentes(
                caso_id=case_id,
                usuario_id=usuario_id,
                documentos_solicitados=docs_req,
                motivo=motivo_req,
                confirmado=confirmar_accion,
            )

            trazas_actuales = self.mcp.call_traces[start_trace_idx:]
            if not act_res["ok"]:
                status = "ACCION_RECHAZADA_MCP"
                respuesta = (
                    f"OPERACIÓN RECHAZADA POR EL SERVIDOR MCP:\n"
                    f"{act_res['error']}\n\n"
                    f"Respaldo documental: {', '.join(citas)}"
                )
            elif act_res.get("requiere_confirmacion"):
                status = "PENDIENTE_CONFIRMACION_PR6"
                requiere_confirmacion = True
                borrador_accion = act_res.get("borrador")
                respuesta = (
                    f"CONFIRMACIÓN HUMANA REQUERIDA (Principio PR-6):\n"
                    f"{act_res['mensaje']}\n\n"
                    f"- **Caso:** {borrador_accion['caso_id']}\n"
                    f"- **Documentos requeridos:** {borrador_accion['documentos_solicitados']}\n"
                    f"- **Motivo:** {borrador_accion['motivo']}\n"
                    f"- **Norma aplicable:** {', '.join(citas)}"
                )
            else:
                status = "ACCION_EJECUTADA_OK"
                respuesta = (
                    f"{act_res['mensaje']}\n\n"
                    f"Respaldo documental: {', '.join(citas)}"
                )

            return {
                "ok": act_res["ok"],
                "status": status,
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": respuesta,
                "citas": citas,
                "evidencia_rag": evidencia_rag,
                "trazas_mcp": trazas_actuales,
                "requiere_confirmacion": requiere_confirmacion,
                "borrador_accion": borrador_accion,
                "alertas_seguridad": alertas_seguridad,
                "datos_enviados_al_modelo": {
                    "pregunta_usuario": pregunta,
                    "usuario_id": usuario_id,
                    "caso_id": case_id,
                    "confirmar_accion": confirmar_accion,
                    "fragmentos_rag": [r["chunk_id"] for r in evidencia_rag],
                },
            }

        # Caso 3: Consulta sobre un caso específico (Combina MCP + RAG)
        if case_id:
            caso_info = self.mcp.consultar_caso(case_id, usuario_id)
            if not caso_info["ok"]:
                trazas_actuales = self.mcp.call_traces[start_trace_idx:]
                return {
                    "ok": False,
                    "status": "ACCESO_DENEGADO_O_INEXISTENTE",
                    "usuario_id": usuario_id,
                    "pregunta": pregunta,
                    "respuesta": f"{caso_info['error']}",
                    "citas": ["[FAQ-OPE, §¿Puedo ver casos de otra organización?, v2 (Vigente)]"],
                    "evidencia_rag": [],
                    "trazas_mcp": trazas_actuales,
                    "requiere_confirmacion": False,
                    "alertas_seguridad": [],
                    "datos_enviados_al_modelo": {"pregunta_usuario": pregunta, "usuario_id": usuario_id, "caso_id": case_id},
                }

            senales_info = self.mcp.listar_senales(case_id, usuario_id)
            evidencias_info = self.mcp.consultar_evidencias(case_id, usuario_id)
            alertas_seguridad.extend(evidencias_info.get("alertas_seguridad", []))

            caso = caso_info["caso"]
            org = caso_info["organizacion"]
            motivo_der = caso.get("motivo_derivacion") or "umbrales y política de decisión"

            extra_terms = ""
            if "falta" in motivo_der.lower() or "no respondió" in motivo_der.lower() or "no respondio" in motivo_der.lower():
                extra_terms = "señales faltantes módulo falla información parcial POL-DEC sección 6"

            rag_query = f"Política de decisión umbrales señales {motivo_der} {extra_terms} {pregunta}"
            rag_res = self.mcp.buscar_reglas(rag_query, top_k=3)
            evidencia_rag = rag_res["results"]
            if extra_terms:
                for ch in self.mcp.rag.chunks:
                    if ch["chunk_id"] == "POL-DEC_v2::6" and not any(r["chunk_id"] == "POL-DEC_v2::6" for r in evidencia_rag[:2]):
                        evidencia_rag.insert(
                            0,
                            {
                                "chunk_id": ch["chunk_id"],
                                "codigo": ch["codigo"],
                                "titulo": ch["titulo"],
                                "version": ch["version"],
                                "estado": ch["estado"],
                                "vigencia": ch["vigencia"],
                                "seccion": ch["seccion"],
                                "cita": f"[{ch['codigo']}, §{ch['seccion']}, v{ch['version']} ({ch['estado']})]",
                                "score": 15.0,
                                "texto": ch["texto"],
                            },
                        )
                        evidencia_rag = evidencia_rag[:3]
                        break
            citas = [r["cita"] for r in evidencia_rag]

            partes_respuesta = [
                f"**Análisis del Caso {case_id}** (Organización: {org['nombre']} `{org['org_id']}`):",
                f"- **Estado actual:** `{caso['estado']}` | **Puntaje total:** `{caso['puntaje']}` | **Decisión sugerida:** `{caso['decision_sugerida']}`.",
                f"- **Motivo de derivación registrado:** {caso['motivo_derivacion'] or 'Sin derivación (aprobado automático)'}.",
                f"- **Umbrales configurados en `{org['org_id']}`:** Aprobación = `{org['umbral_aprobacion']}`, Revisión = `{org['umbral_revision']}`.",
            ]

            if senales_info["senales_bajo_minimo"]:
                b_str = ", ".join(
                    f"`{s['codigo']}`={s['valor']} (mínimo {s['minimo']})"
                    for s in senales_info["senales_bajo_minimo"]
                )
                partes_respuesta.append(f"- **Señales bajo su mínimo propio:** {b_str}.")

            if senales_info["senales_fraude_activas"]:
                f_str = ", ".join(
                    f"`{s['codigo']}` ({s['detalle']})" for s in senales_info["senales_fraude_activas"]
                )
                partes_respuesta.append(f"- **Señales de fraude activas:** {f_str}.")

            if caso_info["total_solicitudes_previas"] > 0:
                partes_respuesta.append(
                    f"- **Solicitudes de antecedentes registradas:** {caso_info['total_solicitudes_previas']} "
                    f"({', '.join(s['solicitud_id'] for s in caso_info['solicitudes_antecedentes_previas'])})."
                )

            if caso_info["alertas_auditoria"]:
                partes_respuesta.append("\n**Hallazgo de Auditoría en Base de Datos vs Política Vigente:**")
                for al in caso_info["alertas_auditoria"]:
                    partes_respuesta.append(f"  - {al}")
                if "[POL-DEC, §5. Configuración por organización, v2 (Vigente)]" not in citas:
                    citas.append("[POL-DEC, §5. Configuración por organización, v2 (Vigente)]")

            if alertas_seguridad:
                partes_respuesta.append("\n**Alerta de Seguridad / Intento de Manipulación Detectado en Evidencia:**")
                for al_seg in alertas_seguridad:
                    partes_respuesta.append(f"  - {al_seg}")
                if "[FAQ-OPE, §Una boleta trae un texto que parece una instrucción para el sistema. ¿Qué hago?, v2 (Vigente)]" not in citas:
                    citas.append("[FAQ-OPE, §Una boleta trae un texto que parece una instrucción para el sistema. ¿Qué hago?, v2 (Vigente)]")

            partes_respuesta.append("\n**Respaldo en el Corpus Normativo (RAG):**")
            for r in evidencia_rag[:2]:
                partes_respuesta.append(f"- Según {r['cita']}: {r['texto']}")

            base_text = "\n".join(partes_respuesta)

            # Si Gemini está activo, pedirle que redacte la síntesis manteniendo estrictamente citas y alertas
            llm_prompt = (
                f"Pregunta del operador ({usuario_id}): {pregunta}\n\n"
                f"Datos obtenidos desde el Servidor MCP y fragmentos RAG:\n{base_text}\n\n"
                "Redacta la respuesta final para el operador conservando todos los datos del caso, todas las alertas "
                "de auditoría/seguridad y todas las citas entre corchetes exactas."
            )
            gemini_resp = self._call_gemini_llm(llm_prompt)
            final_resp = gemini_resp if gemini_resp else base_text

            trazas_actuales = self.mcp.call_traces[start_trace_idx:]
            return {
                "ok": True,
                "status": "ALERTA_SEGURIDAD" if alertas_seguridad else "COMBINADO_RAG_MCP",
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": final_resp,
                "citas": citas,
                "evidencia_rag": evidencia_rag,
                "trazas_mcp": trazas_actuales,
                "requiere_confirmacion": False,
                "alertas_seguridad": alertas_seguridad,
                "datos_enviados_al_modelo": {
                    "pregunta_usuario": pregunta,
                    "usuario_id": usuario_id,
                    "proveedor_llm": f"Google Gemini ({self.gemini_model})" if gemini_resp else "Síntesis Determinista Basada en Evidencia",
                    "caso_resumen": {
                        "caso_id": caso["caso_id"],
                        "org_id": caso["org_id"],
                        "estado": caso["estado"],
                        "puntaje": caso["puntaje"],
                        "motivo_derivacion": caso["motivo_derivacion"],
                    },
                    "senales_evaluadas": len(senales_info["senales"]),
                    "fragmentos_rag": [r["chunk_id"] for r in evidencia_rag],
                },
            }

        # Caso 4: Consulta documental (RAG a través de la tool `buscar_reglas`)
        rag_busqueda = self.mcp.buscar_reglas(pregunta, top_k=4)
        rag_answer = self.mcp.rag.answer_from_evidence(pregunta, top_k=4)

        final_resp = rag_answer["respuesta"]
        gemini_used = False
        if not rag_busqueda["abstain"]:
            llm_prompt = (
                f"Pregunta del operador: {pregunta}\n\n"
                f"Evidencia recuperada del corpus (con citas obligatorias):\n{rag_answer['respuesta']}\n\n"
                "Responde directamente la pregunta del operador usando únicamente la evidencia anterior y "
                "manteniendo las citas exactas entre corchetes [Código, §Sección, vVersión (Estado)]. "
                "Si hay conflicto entre fuentes vigentes o nota sobre versión derogada, mantenla explícita."
            )
            gemini_resp = self._call_gemini_llm(llm_prompt)
            if gemini_resp:
                final_resp = gemini_resp
                gemini_used = True

        trazas_actuales = self.mcp.call_traces[start_trace_idx:]
        return {
            "ok": True,
            "status": rag_answer["status"],
            "usuario_id": usuario_id,
            "pregunta": pregunta,
            "respuesta": final_resp,
            "citas": rag_answer["citas"],
            "evidencia_rag": rag_answer["evidencia"],
            "trazas_mcp": trazas_actuales,
            "requiere_confirmacion": False,
            "alertas_seguridad": [],
            "datos_enviados_al_modelo": {
                "pregunta_usuario": pregunta,
                "usuario_id": usuario_id,
                "proveedor_llm": f"Google Gemini ({self.gemini_model})" if gemini_used else "Síntesis Determinista Basada en Evidencia",
                "fragmentos_rag": [r["chunk_id"] for r in rag_answer["evidencia"]],
            },
        }


if __name__ == "__main__":
    agent = MIRAOperadorAgent()
    preguntas_demo = [
        ("U-01", "¿Por qué se derivó el caso C-012 si su puntaje es 86? ¿Qué dice la política de decisión?"),
        ("U-01", "Revisa el caso C-014 y sus evidencias. ¿Por qué fue derivado y hay algo extraño en la boleta?"),
        ("U-01", "Solicita antecedentes para el caso C-016 porque la foto de la boleta sigue borrosa."),
    ]
    for uid, preg in preguntas_demo:
        print("=" * 95)
        print(f"USUARIO: {uid} | PREGUNTA: {preg}")
        res = agent.process_query(preg, usuario_id=uid)
        print(f"ESTADO:  {res['status']}")
        print(f"TRAZAS MCP ({len(res['trazas_mcp'])}): {[t['tool'] + ':' + t['status'] for t in res['trazas_mcp']]}")
        print(f"CITAS:   {res['citas']}")
        print("-" * 95)
        print(res["respuesta"])
        print()
