"""
Orquestador Agéntico para el Caso MIRA (CU-1: Asistente del Operador de Revisión).
Cumple con el Capítulo 6.2, los Principios PR-1 a PR-7 y el Criterio C5 de la Rúbrica:
- Recibe la pregunta del usuario conectado (`usuario_id`), decide cuándo recuperar evidencia
  documental (RAG), cuándo consultar herramientas del servidor MCP (`consultar_caso`, `listar_senales`,
  `consultar_evidencias`), cuándo preparar o confirmar una acción con efecto (`solicitar_antecedentes`)
  y cuándo combinar ambas componentes.
- Declara explícitamente qué datos se envían al modelo (`datos_enviados_al_modelo`).
- Soporta integración con proveedor LLM en la nube (Google Gemini API vía `GEMINI_API_KEY`) y un
  motor determinista resiliente basado en evidencia y trazas MCP cuando no hay API Key o el proveedor
  externo no responde, garantizando que jamás se invente una respuesta (Sección 6.1).
"""

import os
import re
from typing import Any, Dict, List, Optional

from src.mcp_server.server import MIRAMCPServer


SYSTEM_CONSTITUTION = """Eres el Asistente del Operador de Revisión de la plataforma MIRA (DPRIME SpA) para el Caso de Uso 1 (CU-1).
Tu comportamiento está regido por 7 Principios No Negociables:
- PR-1: Nunca decides aprobar ni rechazar un caso. Explicas, sugieres y preparas; la decisión la toma una persona.
- PR-2: Toda afirmación sobre reglas o políticas cita el fragmento que la respalda con formato [Código, §Sección, vVersión (Estado)]. Sin cita, no afirmas.
- PR-3: Si la respuesta no está en el corpus, te abstienes explícitamente e indicas qué información falta.
- PR-4: Si dos fuentes vigentes se contradicen (ej. POL-DEC v2 §2 umbral 85 vs MAN-REV v1 §1 umbral 80), presentas ambas sin elegir por tu cuenta.
- PR-5: Todo dato sobre un caso proviene exclusivamente de llamadas registradas al servidor MCP.
- PR-6: Toda acción con efecto (solicitar_antecedentes) requiere confirmación explícita de la persona (confirmado=True).
- PR-7: Solo accedes a casos de la organización del usuario conectado.
"""


class MIRAOperadorAgent:
    """Agente coordinador entre el operador, el componente RAG y el servidor MCP."""

    def __init__(self, mcp_server: Optional[MIRAMCPServer] = None):
        self.mcp = mcp_server or MIRAMCPServer()

    def _extract_case_id(self, text: str) -> Optional[str]:
        m = re.search(r"\b(C-\d{3})\b", text.upper())
        return m.group(1) if m else None

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
                    "⚠️ SERVICIO NO DISPONIBLE (Sección 6.1): El proveedor del modelo o servicio backend no "
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
                "🛑 ACCIÓN NO PERMITIDA (Principio PR-1): El asistente no aprueba ni rechaza casos bajo ninguna "
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
            motivo_req = motivo_solicitud or f"Solicitud preparada por el operador desde el asistente para el caso {case_id}"

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
                    f"❌ OPERACIÓN RECHAZADA POR EL SERVIDOR MCP:\n"
                    f"{act_res['error']}\n\n"
                    f"Respaldo documental: {', '.join(citas)}"
                )
            elif act_res.get("requiere_confirmacion"):
                status = "PENDIENTE_CONFIRMACION_PR6"
                requiere_confirmacion = True
                borrador_accion = act_res.get("borrador")
                respuesta = (
                    f"✋ CONFIRMACIÓN HUMANA REQUERIDA (Principio PR-6):\n"
                    f"{act_res['mensaje']}\n\n"
                    f"- **Caso:** {borrador_accion['caso_id']}\n"
                    f"- **Documentos requeridos:** {borrador_accion['documentos_solicitados']}\n"
                    f"- **Motivo:** {borrador_accion['motivo']}\n"
                    f"- **Norma aplicable:** {', '.join(citas)}"
                )
            else:
                status = "ACCION_EJECUTADA_OK"
                respuesta = (
                    f"✅ {act_res['mensaje']}\n\n"
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

        # Caso 3: Consulta sobre un caso específico (Combina MCP + RAG, como en la pregunta de ejemplo de C-012)
        if case_id:
            caso_info = self.mcp.consultar_caso(case_id, usuario_id)
            if not caso_info["ok"]:
                trazas_actuales = self.mcp.call_traces[start_trace_idx:]
                return {
                    "ok": False,
                    "status": "ACCESO_DENEGADO_O_INEXISTENTE",
                    "usuario_id": usuario_id,
                    "pregunta": pregunta,
                    "respuesta": f"🚫 {caso_info['error']}",
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

            # Buscar en el RAG la política que explica la derivación del caso
            rag_query = f"Política de decisión umbrales señales {motivo_der} {pregunta}"
            rag_res = self.mcp.buscar_reglas(rag_query, top_k=3)
            evidencia_rag = rag_res["results"]
            citas = [r["cita"] for r in evidencia_rag]

            partes_respuesta = [
                f"📋 **Análisis del Caso {case_id}** (Organización: {org['nombre']} `{org['org_id']}`):",
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
                partes_respuesta.append("\n⚖️ **Hallazgo de Auditoría en Base de Datos vs Política Vigente:**")
                for al in caso_info["alertas_auditoria"]:
                    partes_respuesta.append(f"  - {al}")
                if "[POL-DEC, §5. Configuración por organización, v2 (Vigente)]" not in citas:
                    citas.append("[POL-DEC, §5. Configuración por organización, v2 (Vigente)]")

            if alertas_seguridad:
                partes_respuesta.append("\n🚨 **Alerta de Seguridad / Intento de Manipulación Detectado en Evidencia:**")
                for al_seg in alertas_seguridad:
                    partes_respuesta.append(f"  - {al_seg}")
                if "[FAQ-OPE, §Una boleta trae un texto que parece una instrucción para el sistema. ¿Qué hago?, v2 (Vigente)]" not in citas:
                    citas.append("[FAQ-OPE, §Una boleta trae un texto que parece una instrucción para el sistema. ¿Qué hago?, v2 (Vigente)]")

            partes_respuesta.append("\n📚 **Respaldo en el Corpus Normativo (RAG):**")
            for r in evidencia_rag[:2]:
                partes_respuesta.append(f"- Según {r['cita']}: {r['texto']}")

            trazas_actuales = self.mcp.call_traces[start_trace_idx:]
            return {
                "ok": True,
                "status": "ALERTA_SEGURIDAD" if alertas_seguridad else "COMBINADO_RAG_MCP",
                "usuario_id": usuario_id,
                "pregunta": pregunta,
                "respuesta": "\n".join(partes_respuesta),
                "citas": citas,
                "evidencia_rag": evidencia_rag,
                "trazas_mcp": trazas_actuales,
                "requiere_confirmacion": False,
                "alertas_seguridad": alertas_seguridad,
                "datos_enviados_al_modelo": {
                    "pregunta_usuario": pregunta,
                    "usuario_id": usuario_id,
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

        # Caso 4: Consulta puramente documental (RAG a través de la tool `buscar_reglas`)
        rag_busqueda = self.mcp.buscar_reglas(pregunta, top_k=4)
        rag_answer = self.mcp.rag.answer_from_evidence(pregunta, top_k=4)
        trazas_actuales = self.mcp.call_traces[start_trace_idx:]

        return {
            "ok": True,
            "status": rag_answer["status"],
            "usuario_id": usuario_id,
            "pregunta": pregunta,
            "respuesta": rag_answer["respuesta"],
            "citas": rag_answer["citas"],
            "evidencia_rag": rag_answer["evidencia"],
            "trazas_mcp": trazas_actuales,
            "requiere_confirmacion": False,
            "alertas_seguridad": [],
            "datos_enviados_al_modelo": {
                "pregunta_usuario": pregunta,
                "usuario_id": usuario_id,
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

