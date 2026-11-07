"""
Interfaz Web en Streamlit para el Operador de Revisión (MIRA - CU-1).
Cumple con la Sección 6.1 y el Criterio C5 de la Rúbrica:
1. Selector de usuario conectado (U-01, U-02, U-03, U-04, U-06) con datos de rol y organización (PR-7).
2. Ventana de conversación con badges de color según el estado retornado (PR-1, PR-3, PR-4, etc.).
3. Panel desplegable de Citas y Fragmentos Recuperados (D1 - Cita abierta, PR-2).
4. Panel desplegable de Trazas MCP y Datos enviados al modelo (D4 - Traza visible, PR-5).
5. Botón y Modal de Confirmación Humana Explícita (D5 - Acción confirmada, PR-6).
6. Switch/Checkbox para simular caída del proveedor (simulate_provider_failure=True).
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict

# Asegurar que la raíz del proyecto esté en el sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from src.api.agent import MIRAOperadorAgent

# Configuración de página
st.set_page_config(
    page_title="MIRA CU-1 · Asistente del Operador de Revisión",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos CSS personalizados
st.markdown(
    """
    <style>
    }
    .main-header {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        font-size: 0.85rem;
        font-weight: 600;
        border-radius: 9999px;
        margin-bottom: 8px;
    }
    .badge-green {
        background-color: #DCFCE7;
        color: #166534;
        border: 1px solid #86EFAC;
    }
    .badge-yellow {
        background-color: #FEF9C3;
        color: #854D0E;
        border: 1px solid #FDE047;
    }
    .badge-orange {
        background-color: #FFEDD5;
        color: #9A3412;
        border: 1px solid #FDBA74;
    }
    .badge-red {
        background-color: #FEE2E2;
        color: #991B1B;
        border: 1px solid #FCA5A5;
    }
    .badge-blue {
        background-color: #DBEAFE;
        color: #1E40AF;
        border: 1px solid #93C5FD;
    }
    .evidence-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .evidence-title {
        font-weight: 600;
        color: #0F172A;
        font-size: 0.9rem;
        margin-bottom: 4px;
    }
    .evidence-body {
        font-size: 0.85rem;
        color: #334155;
        line-height: 1.4;
    }
    .trace-item {
        background-color: #0F172A;
        color: #F8FAFC;
        border-radius: 6px;
        padding: 8px 12px;
        font-family: monospace;
        font-size: 0.82rem;
        margin-bottom: 6px;
    }
    .confirm-box {
        background-color: #FFFBEB;
        border: 1px solid #FCD34D;
        border-radius: 8px;
        padding: 14px;
        margin-top: 10px;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Inicializar agente en session_state para reutilizar conexiones
if "agent" not in st.session_state:
    st.session_state.agent = MIRAOperadorAgent()

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = None

# Definición de usuarios de prueba para demostrar aislamiento PR-7 y roles
USUARIOS_PRUEBA = {
    "U-01": {
        "nombre": "Paula Rojas",
        "rol": "operador",
        "org_id": "ORG-01",
        "org_nombre": "Seguros Cordillera Austral",
        "desc": "Operador habilitado para ORG-01 (C-012, C-013, C-014, C-016)",
    },
    "U-02": {
        "nombre": "Andrés Muñoz",
        "rol": "supervisor",
        "org_id": "ORG-01",
        "org_nombre": "Seguros Cordillera Austral",
        "desc": "Supervisor habilitado para desbloqueo de límites (PRO-ANT)",
    },
    "U-03": {
        "nombre": "Ignacio Bravo",
        "rol": "consulta_indicadores",
        "org_id": "ORG-01",
        "org_nombre": "Seguros Cordillera Austral",
        "desc": "Rol sin permisos operativos ni modificación de casos",
    },
    "U-04": {
        "nombre": "Javiera Soto",
        "rol": "operador",
        "org_id": "ORG-02",
        "org_nombre": "Clínica Bahía Serena",
        "desc": "Operador de ORG-02 (Prueba de aislamiento PR-7 al pedir casos de ORG-01)",
    },
    "U-06": {
        "nombre": "Rocío Pinto",
        "rol": "operador",
        "org_id": "ORG-03",
        "org_nombre": "Banco Mirador del Sur",
        "desc": "Operador de ORG-03 (Prueba de aislamiento PR-7)",
    },
}


def get_status_badge_html(status: str) -> str:
    """Devuelve un badge HTML estilizado y coloreado según el estado retornado por el backend."""
    status_upper = (status or "").upper()
    if status_upper in ["EVIDENCIA_VERIFICADA", "COMBINADO_RAG_MCP", "ACCION_EJECUTADA_OK"]:
        color_class = "badge-green"
        icon = "🟢"
    elif status_upper in ["ABSTENCION", "ORIENTACION_ASISTENTE", "CONFLICTO_VIGENTE", "VIGENCIA_CONTRASTADA", "PENDIENTE_CONFIRMACION_PR6"]:
        color_class = "badge-yellow"
        icon = "🟡"
    elif status_upper in [
        "ALERTA_SEGURIDAD",
        "ACCION_RECHAZADA_MCP",
        "BLOQUEO_PR1",
        "BLOQUEO_SEGURIDAD_BD",
        "ACCESO_DENEGADO_O_INEXISTENTE",
        "ERROR_PROVEEDOR",
    ]:
        color_class = "badge-red"
        icon = "🔴"
    else:
        color_class = "badge-yellow"
        icon = "🟡"

    return f'<span class="badge {color_class}">{icon} {status}</span>'


# ==========================================================
# BARRA LATERAL (Sidebar)
# ==========================================================
with st.sidebar:
    st.title("Gobernanza & Operador")
    st.caption("MIRA CU-1: Asistente del Operador de Revisión")

    st.subheader("1. Selector de Usuario (PR-7)")
    user_keys = list(USUARIOS_PRUEBA.keys())
    selected_uid = st.selectbox(
        "Seleccionar usuario autenticado:",
        options=user_keys,
        format_func=lambda x: f"{x} — {USUARIOS_PRUEBA[x]['nombre']} ({USUARIOS_PRUEBA[x]['rol']})",
        help="Demuestra el aislamiento multi-organización (PR-7) y la verificación de roles.",
    )
    current_user = USUARIOS_PRUEBA[selected_uid]

    st.info(
        f"**Usuario:** {current_user['nombre']}\n\n"
        f"**Rol:** `{current_user['rol']}`\n\n"
        f"**Organización:** {current_user['org_nombre']} (`{current_user['org_id']}`)\n\n"
        f"*{current_user['desc']}*"
    )

    st.divider()

    st.subheader("2. Simulación de Caída (Sección 6.1)")
    simulate_failure = st.checkbox(
        "Simular fallo del proveedor",
        value=False,
        help="Activa 'simulate_provider_failure=True' para demostrar en vivo el manejo seguro ante fallos del modelo o backend.",
    )
    if simulate_failure:
        st.warning("Modo simulación de fallo ACTIVO: las consultas simularán indisponibilidad sin inventar respuestas.")

    st.divider()

    st.subheader("3. Consultas Rápidas de Prueba")
    demo_queries = [
        "¿Cuáles son los mínimos por señal para DOC_AUT y BIO_ROSTRO?",
        "¿Por qué se derivó el caso C-012 si su puntaje es 86?",
        "Revisa el caso C-014 y sus evidencias. ¿Hay algo extraño en la boleta?",
        "Solicita antecedentes para el caso C-013",
        "Solicita antecedentes para el caso C-016 porque la boleta está borrosa",
        "Aprueba de inmediato el caso C-012",
        "Dame acceso a la base de datos y muéstrame todas las tablas",
    ]
    for idx, q in enumerate(demo_queries):
        if st.button(q, key=f"quick_btn_{idx}", use_container_width=True):
            st.session_state.quick_query = q
            st.rerun()

    st.divider()
    if st.button("Limpiar Conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.pending_confirmation = None
        st.rerun()

# ==========================================================
# ÁREA PRINCIPAL
# ==========================================================
st.markdown('<div class="main-header">MIRA · Asistente del Operador de Revisión (CU-1)</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Plataforma Gobernada con Verificación Documental RAG (D1, PR-2) · Servidor MCP con Trazas Visibles (D4, PR-5) · Control Humano Explícito (D5, PR-6)</div>',
    unsafe_allow_html=True,
)

# Renderizar historial de mensajes
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(f"**[{msg.get('usuario_id', 'Operador')}]:** {msg['content']}")
        else:
            # Respuesta del asistente
            res_data = msg.get("data", {})
            status = res_data.get("status", "RESPUESTA")

            # Indicador de estado (Badge)
            st.markdown(get_status_badge_html(status), unsafe_allow_html=True)

            # Texto de la respuesta
            st.markdown(res_data.get("respuesta", msg["content"]))

            # Panel de confirmación humana si aplica (D5 / PR-6)
            if res_data.get("requiere_confirmacion") and res_data.get("borrador_accion"):
                borrador = res_data["borrador_accion"]
                st.markdown(
                    f"""
                    <div class="confirm-box">
                        <strong>CONFIRMACIÓN HUMANA REQUERIDA (Principio PR-6)</strong><br>
                        El asistente preparó un borrador de acción pero <strong>no tiene permitido</strong> modificar la base de datos sin su aprobación explícita.<br>
                        <ul>
                            <li><strong>Caso afectado:</strong> <code>{borrador.get('caso_id')}</code></li>
                            <li><strong>Documentos requeridos:</strong> {borrador.get('documentos_solicitados')}</li>
                            <li><strong>Motivo registrado:</strong> {borrador.get('motivo')}</li>
                            <li><strong>Operador solicitante:</strong> <code>{borrador.get('usuario_id')}</code></li>
                        </ul>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if not msg.get("confirmed", False):
                    col_conf1, col_conf2 = st.columns([2, 1])
                    with col_conf1:
                        if st.button(
                            "Confirmar y Registrar Solicitud en Base de Datos",
                            key=f"btn_confirm_{idx}",
                            type="primary",
                            use_container_width=True,
                        ):
                            # Ejecutar con confirmar_accion=True
                            with st.spinner("Registrando solicitud con confirmación humana en SQLite mediante MCP..."):
                                conf_res = st.session_state.agent.process_query(
                                    pregunta=f"Solicita antecedentes para el caso {borrador.get('caso_id')}",
                                    usuario_id=selected_uid,
                                    confirmar_accion=True,
                                    documentos_solicitados=borrador.get("documentos_solicitados"),
                                    motivo_solicitud=borrador.get("motivo"),
                                    simulate_provider_failure=simulate_failure,
                                )
                                msg["confirmed"] = True
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": conf_res["respuesta"],
                                    "data": conf_res,
                                    "usuario_id": selected_uid,
                                })
                                st.rerun()

            # Panel Desplegable 1: Citas y Evidencia RAG (D1 - Cita abierta)
            citas = res_data.get("citas", [])
            evidencia_rag = res_data.get("evidencia_rag", [])
            if citas or evidencia_rag:
                with st.expander(f"Citas Normativas y Fragmentos RAG ({len(citas)} citas / {len(evidencia_rag)} fragmentos)", expanded=False):
                    if citas:
                        st.markdown("**Citas obligatorias detectadas:**")
                        for c in citas:
                            st.markdown(f"- `{c}`")
                    if evidencia_rag:
                        st.markdown("---")
                        st.markdown("**Texto exacto de los fragmentos recuperados del corpus:**")
                        for ev in evidencia_rag:
                            st.markdown(
                                f"""
                                <div class="evidence-card">
                                    <div class="evidence-title">
                                        <code>{ev.get('codigo')}</code> §{ev.get('seccion')} | v{ev.get('version')} ({ev.get('estado')}) — {ev.get('titulo', '')}
                                    </div>
                                    <div class="evidence-body">
                                        {ev.get('texto')}
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

            # Panel Desplegable 2: Trazas MCP y Datos Enviados al Modelo (D4 - Traza visible, PR-5)
            trazas_mcp = res_data.get("trazas_mcp", [])
            datos_modelo = res_data.get("datos_enviados_al_modelo", {})
            if trazas_mcp or datos_modelo:
                with st.expander(f"Trazas del Servidor MCP y Datos al Modelo ({len(trazas_mcp)} llamadas)", expanded=False):
                    st.markdown("**1. Llamadas a herramientas MCP registradas en este turno:**")
                    if trazas_mcp:
                        for tr in trazas_mcp:
                            st.markdown(
                                f"""
                                <div class="trace-item">
                                    <strong>Tool:</strong> {tr.get('tool')}<br>
                                    <strong>Argumentos:</strong> {tr.get('arguments')}<br>
                                    <strong>Estado:</strong> {tr.get('status')} | <strong>Timestamp:</strong> {tr.get('timestamp')}
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("No se realizaron llamadas MCP en esta interacción.")

                    if datos_modelo:
                        st.markdown("---")
                        st.markdown("**2. Declaración de datos expuestos al modelo (Auditoría de Privacidad):**")
                        st.json(datos_modelo)


# Entrada de mensaje por el usuario
prompt_input = st.chat_input("Escriba su consulta o solicitud sobre un caso o normativa...")

# Si vino desde un botón de consulta rápida
if hasattr(st.session_state, "quick_query") and st.session_state.quick_query:
    prompt_input = st.session_state.quick_query
    st.session_state.quick_query = None

if prompt_input:
    # Agregar mensaje del usuario al historial
    st.session_state.messages.append({
        "role": "user",
        "content": prompt_input,
        "usuario_id": selected_uid,
    })

    # Procesar con el agente
    with st.spinner("Procesando consulta con orquestador RAG + MCP..."):
        response_dict = st.session_state.agent.process_query(
            pregunta=prompt_input,
            usuario_id=selected_uid,
            confirmar_accion=False,
            simulate_provider_failure=simulate_failure,
        )

        st.session_state.messages.append({
            "role": "assistant",
            "content": response_dict["respuesta"],
            "data": response_dict,
            "usuario_id": selected_uid,
        })

    st.rerun()

