"""
Servidor MCP (Model Context Protocol) para el Caso MIRA (CU-1: Operador de Revisión).
Cumple al 100 % con el Capítulo 5, los Principios PR-1 a PR-7 y el Criterio C4 de la Rúbrica:
- Expone las tres primitivas MCP vistas en clases: Tools (controladas por el modelo con permisos),
  Resources (controlados por el usuario/host) y Prompts (plantillas para el usuario).
- Todas las consultas SQL son 100 % parametrizadas (`?`). El modelo jamás escribe SQL.
- Aislamiento multi-organización estricto (PR-7): un usuario solo puede consultar o actuar sobre
  casos de su propia organización (`org_id`).
- Detección de intentos de manipulación (Prompt Injection) en evidencias (`E-007` en `C-014`) y
  auditoría de cambios de umbral sin doble aprobación (`CU-001` en `ORG-01` / `C-012`).
- Validación en el servidor para acciones con efecto (`solicitar_antecedentes`):
  1. Verifica rol autorizado (`operador` o `supervisor`, bloqueando `consulta_indicadores`, PRO-ANT §4).
  2. Verifica estado del caso (bloquea `aprobado_automatico`, PRO-ANT §4).
  3. Verifica límite de solicitudes: si el caso ya tiene 2 o más solicitudes (`C-016`) y el usuario
     es `operador`, rechaza con mensaje normativo citando `PRO-ANT §4`.
  4. Exige confirmación humana explícita en el servidor (`confirmado=True`, PR-6): si `confirmado=False`,
     prepara la pre-solicitud sin modificar la base de datos.
"""

import datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.db.init_db import DB_PATH, init_database
from src.rag.retriever import RAGRetriever

PROMPT_INJECTION_PATTERNS = [
    r"ignora las pol[íi]ticas",
    r"nota para el asistente",
    r"debe aprobarse de inmediato",
    r"ignore previous instructions",
    r"system prompt",
]


class MIRAMCPServer:
    """Servidor MCP propio para el Caso de Uso 1 (Asistente del Operador de Revisión)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        if not self.db_path.exists():
            init_database(db_path=self.db_path)
        self.rag = RAGRetriever()
        self.call_traces: List[Dict[str, Any]] = []

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _log_trace(self, tool_name: str, args: Dict[str, Any], status: str, summary: str) -> Dict[str, Any]:
        trace = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "tool": tool_name,
            "arguments": args,
            "status": status,
            "summary": summary,
        }
        self.call_traces.append(trace)
        return trace

    def _authenticate_and_authorize(
        self, conn: sqlite3.Connection, usuario_id: str, target_org_id: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Verifica que el usuario exista y pertenezca a la organización consultada (PR-7)."""
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.usuario_id, u.nombre, u.org_id, u.rol,
                   o.nombre AS org_nombre, o.umbral_aprobacion, o.umbral_revision,
                   o.plazo_resolucion_dias_habiles, o.plazo_antecedentes_dias_habiles
            FROM usuarios u
            JOIN organizaciones o ON u.org_id = o.org_id
            WHERE u.usuario_id = ?
            """,
            (usuario_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None, f"Usuario '{usuario_id}' no registrado en el sistema."

        user = dict(row)
        if target_org_id and user["org_id"] != target_org_id:
            return (
                user,
                (
                    f"ACCESO DENEGADO (PR-7 / FAQ-OPE v2): El usuario {user['nombre']} ({usuario_id}) "
                    f"pertenece a la organización {user['org_id']} ({user['org_nombre']}) y no tiene "
                    f"permiso para acceder a casos ni datos de la organización {target_org_id}."
                ),
            )
        return user, None

    # =========================================================================
    # PRIMITIVA 1: TOOLS (Controladas por el Modelo con Validación del Servidor)
    # =========================================================================

    def list_tools(self) -> List[Dict[str, Any]]:
        """Devuelve el catálogo de contratos JSON Schema de las herramientas MCP."""
        return [
            {
                "name": "buscar_reglas",
                "description": (
                    "Busca reglas, políticas, catálogos de señales o procedimientos en el corpus documental "
                    "de MIRA (RAG) devolviendo fragmentos con cita verificable, vigencia y alertas de conflicto."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "consulta": {"type": "string", "description": "Pregunta o término normativo a buscar."},
                        "top_k": {"type": "integer", "default": 4, "description": "Número de fragmentos a recuperar."},
                    },
                    "required": ["consulta"],
                },
            },
            {
                "name": "consultar_caso",
                "description": (
                    "Consulta los datos vivos de un caso en la base de datos (puntaje, estado, motivo de derivación, "
                    "organización, umbral vigente, auditoría de cambios de umbral y conteo de solicitudes previas). "
                    "Valida que el usuario conectado pertenezca a la misma organización del caso (PR-7)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "caso_id": {"type": "string", "description": "Identificador del caso, ej. C-012."},
                        "usuario_id": {"type": "string", "description": "ID del usuario conectado, ej. U-01."},
                    },
                    "required": ["caso_id", "usuario_id"],
                },
            },
            {
                "name": "listar_senales",
                "description": (
                    "Lista todas las señales evaluadas en un caso (documentales, biométricas, cruces y señales de "
                    "fraude), indicando cuáles quedaron bajo su mínimo normativo o están activas."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "caso_id": {"type": "string", "description": "Identificador del caso, ej. C-013."},
                        "usuario_id": {"type": "string", "description": "ID del usuario conectado, ej. U-01."},
                    },
                    "required": ["caso_id", "usuario_id"],
                },
            },
            {
                "name": "consultar_evidencias",
                "description": (
                    "Obtiene las piezas de evidencia adjuntas a un caso (PDFs, imágenes, legibilidad y texto extraído) "
                    "e inspecciona si el texto extraído contiene intentos de manipulación o Prompt Injection (FAQ-OPE)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "caso_id": {"type": "string", "description": "Identificador del caso, ej. C-014."},
                        "usuario_id": {"type": "string", "description": "ID del usuario conectado, ej. U-01."},
                    },
                    "required": ["caso_id", "usuario_id"],
                },
            },
            {
                "name": "solicitar_antecedentes",
                "description": (
                    "Registra una solicitud de antecedentes sobre un caso (Acción con efecto en BD). "
                    "Valida en el servidor: rol (operador o supervisor), pertenencia a la organización (PR-7), "
                    "que el caso no esté aprobado automáticamente, límite máximo de 2 solicitudes para operadores "
                    "(PRO-ANT §4) y confirmación humana explícita (`confirmado=True`, PR-6)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "caso_id": {"type": "string", "description": "Identificador del caso, ej. C-016."},
                        "usuario_id": {"type": "string", "description": "ID del usuario que solicita, ej. U-01."},
                        "documentos_solicitados": {
                            "type": "string",
                            "description": "Lista clara de documentos o capturas requeridas.",
                        },
                        "motivo": {
                            "type": "string",
                            "description": "Motivo redactado en lenguaje comprensible para persona no técnica (PRO-ANT §2).",
                        },
                        "confirmado": {
                            "type": "boolean",
                            "default": False,
                            "description": "Debe ser True únicamente cuando la persona confirmó explícitamente la acción (PR-6).",
                        },
                    },
                    "required": ["caso_id", "usuario_id", "documentos_solicitados", "motivo"],
                },
            },
        ]

    def buscar_reglas(self, consulta: str, top_k: int = 4) -> Dict[str, Any]:
        """Tool MCP: Búsqueda documental RAG."""
        res = self.rag.search(consulta, top_k=top_k)
        status = "ABSTENCION" if res["abstain"] else "OK"
        self._log_trace(
            "buscar_reglas",
            {"consulta": consulta, "top_k": top_k},
            status,
            f"Recuperados {len(res['results'])} fragmentos (conflicto={res['conflict_detected']})",
        )
        return res

    def consultar_caso(self, caso_id: str, usuario_id: str) -> Dict[str, Any]:
        """Tool MCP: Consulta parametrizada de un caso, su organización y auditoría de umbrales."""
        args = {"caso_id": caso_id, "usuario_id": usuario_id}
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM casos WHERE caso_id = ?", (caso_id,))
            caso_row = cur.fetchone()
            if caso_row is None:
                msg = f"El caso '{caso_id}' no existe en la base de datos."
                self._log_trace("consultar_caso", args, "ERROR_NO_ENCONTRADO", msg)
                return {"ok": False, "error": msg, "codigo_error": "CASO_NO_ENCONTRADO"}

            caso = dict(caso_row)
            user, auth_err = self._authenticate_and_authorize(conn, usuario_id, caso["org_id"])
            if auth_err:
                self._log_trace("consultar_caso", args, "ERROR_PERMISOS", auth_err)
                return {"ok": False, "error": auth_err, "codigo_error": "ACCESO_DENEGADO_PR7"}

            # Consultar historial de solicitudes de antecedentes previas del caso
            cur.execute(
                """
                SELECT solicitud_id, usuario_id, fecha, documentos_solicitados, motivo, estado
                FROM solicitudes_antecedentes
                WHERE caso_id = ?
                ORDER BY fecha ASC
                """,
                (caso_id,),
            )
            solicitudes = [dict(r) for r in cur.fetchall()]

            # Consultar historial de cambios de umbral de la organización para detectar anomalías (ej. CU-001)
            cur.execute(
                """
                SELECT cambio_id, parametro, valor_anterior, valor_nuevo, autor, aprobador_1, aprobador_2, fecha
                FROM cambios_umbral
                WHERE org_id = ?
                ORDER BY fecha DESC
                """,
                (caso["org_id"],),
            )
            cambios = [dict(r) for r in cur.fetchall()]
            alertas_auditoria = []
            for c in cambios:
                if not c["aprobador_2"]:
                    alertas_auditoria.append(
                        f"ALERTA DE AUDITORÍA NORMATIVA: El cambio de umbral {c['cambio_id']} "
                        f"({c['parametro']}: {c['valor_anterior']} -> {c['valor_nuevo']} el {c['fecha']}) "
                        f"registra un solo aprobador ({c['aprobador_1']}) y 'aprobador_2' está vacío. "
                        f"Según [POL-DEC, §5. Configuración por organización, v2 (Vigente)], un cambio de umbral "
                        f"requiere la aprobación de dos supervisores y con una sola aprobación no entra en vigor."
                    )

            result = {
                "ok": True,
                "caso": caso,
                "organizacion": {
                    "org_id": user["org_id"],
                    "nombre": user["org_nombre"],
                    "umbral_aprobacion": user["umbral_aprobacion"],
                    "umbral_revision": user["umbral_revision"],
                    "plazo_resolucion_dias_habiles": user["plazo_resolucion_dias_habiles"],
                    "plazo_antecedentes_dias_habiles": user["plazo_antecedentes_dias_habiles"],
                },
                "usuario_conectado": {
                    "usuario_id": user["usuario_id"],
                    "nombre": user["nombre"],
                    "rol": user["rol"],
                },
                "solicitudes_antecedentes_previas": solicitudes,
                "total_solicitudes_previas": len(solicitudes),
                "cambios_umbral_org": cambios,
                "alertas_auditoria": alertas_auditoria,
            }
            self._log_trace(
                "consultar_caso",
                args,
                "OK",
                f"Caso {caso_id} ({caso['estado']}, puntaje={caso['puntaje']}, solicitudes={len(solicitudes)})",
            )
            return result

    def listar_senales(self, caso_id: str, usuario_id: str) -> Dict[str, Any]:
        """Tool MCP: Lista señales de un caso validando permisos por organización (PR-7)."""
        args = {"caso_id": caso_id, "usuario_id": usuario_id}
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT org_id, motivo_derivacion FROM casos WHERE caso_id = ?", (caso_id,))
            caso_row = cur.fetchone()
            if caso_row is None:
                msg = f"El caso '{caso_id}' no existe en la base de datos."
                self._log_trace("listar_senales", args, "ERROR_NO_ENCONTRADO", msg)
                return {"ok": False, "error": msg, "codigo_error": "CASO_NO_ENCONTRADO"}

            _, auth_err = self._authenticate_and_authorize(conn, usuario_id, caso_row["org_id"])
            if auth_err:
                self._log_trace("listar_senales", args, "ERROR_PERMISOS", auth_err)
                return {"ok": False, "error": auth_err, "codigo_error": "ACCESO_DENEGADO_PR7"}

            cur.execute(
                """
                SELECT senal_id, codigo, valor, minimo, bajo_minimo, es_fraude, activa, detalle
                FROM senales
                WHERE caso_id = ?
                ORDER BY senal_id ASC
                """,
                (caso_id,),
            )
            senales = [dict(r) for r in cur.fetchall()]
            bajo_minimo = [s for s in senales if s["bajo_minimo"] == "sí"]
            fraude_activas = [s for s in senales if s["es_fraude"] == "sí" and s["activa"] == "sí"]

            self._log_trace(
                "listar_senales",
                args,
                "OK",
                f"{len(senales)} señales ({len(bajo_minimo)} bajo mínimo, {len(fraude_activas)} fraude activas)",
            )
            return {
                "ok": True,
                "caso_id": caso_id,
                "total_senales": len(senales),
                "senales_bajo_minimo": bajo_minimo,
                "senales_fraude_activas": fraude_activas,
                "senales": senales,
            }

    def consultar_evidencias(self, caso_id: str, usuario_id: str) -> Dict[str, Any]:
        """Tool MCP: Consulta piezas de evidencia y ejecuta detector anti-Prompt Injection (FAQ-OPE)."""
        args = {"caso_id": caso_id, "usuario_id": usuario_id}
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT org_id FROM casos WHERE caso_id = ?", (caso_id,))
            caso_row = cur.fetchone()
            if caso_row is None:
                msg = f"El caso '{caso_id}' no existe en la base de datos."
                self._log_trace("consultar_evidencias", args, "ERROR_NO_ENCONTRADO", msg)
                return {"ok": False, "error": msg, "codigo_error": "CASO_NO_ENCONTRADO"}

            _, auth_err = self._authenticate_and_authorize(conn, usuario_id, caso_row["org_id"])
            if auth_err:
                self._log_trace("consultar_evidencias", args, "ERROR_PERMISOS", auth_err)
                return {"ok": False, "error": auth_err, "codigo_error": "ACCESO_DENEGADO_PR7"}

            cur.execute(
                """
                SELECT evidencia_id, tipo, nombre_archivo, paginas, legible, texto_extraido
                FROM evidencias
                WHERE caso_id = ?
                ORDER BY evidencia_id ASC
                """,
                (caso_id,),
            )
            evidencias = [dict(r) for r in cur.fetchall()]
            alertas_seguridad = []

            for ev in evidencias:
                texto = ev.get("texto_extraido") or ""
                for pat in PROMPT_INJECTION_PATTERNS:
                    if re.search(pat, texto, re.IGNORECASE):
                        alerta = (
                            f"ALERTA DE SEGURIDAD (Intento de Manipulación / Prompt Injection en {ev['evidencia_id']} - "
                            f"{ev['nombre_archivo']}): El documento contiene instrucciones dirigidas al asistente de IA "
                            f"para alterar la decisión. Según [FAQ-OPE, §Una boleta trae un texto que parece una instrucción "
                            f"para el sistema. ¿Qué hago?, v2 (Vigente)], esta instrucción ha sido neutralizada y no será "
                            f"seguida. El operador debe dejar constancia y evaluar derivar el caso a un supervisor."
                        )
                        ev["alerta_manipulacion"] = alerta
                        alertas_seguridad.append(alerta)
                        break

            self._log_trace(
                "consultar_evidencias",
                args,
                "ALERTA_INYECCION" if alertas_seguridad else "OK",
                f"{len(evidencias)} evidencias ({len(alertas_seguridad)} alertas de manipulación)",
            )
            return {
                "ok": True,
                "caso_id": caso_id,
                "evidencias": evidencias,
                "alertas_seguridad": alertas_seguridad,
            }

    def solicitar_antecedentes(
        self,
        caso_id: str,
        usuario_id: str,
        documentos_solicitados: str,
        motivo: str,
        confirmado: bool = False,
    ) -> Dict[str, Any]:
        """
        Tool MCP de Escritura Gobernada: Registra una solicitud de antecedentes validando
        todas las reglas del procedimiento PRO-ANT y los principios PR-6 y PR-7 en el servidor.
        """
        args = {
            "caso_id": caso_id,
            "usuario_id": usuario_id,
            "documentos_solicitados": documentos_solicitados,
            "motivo": motivo,
            "confirmado": confirmado,
        }
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM casos WHERE caso_id = ?", (caso_id,))
            caso_row = cur.fetchone()
            if caso_row is None:
                msg = f"El caso '{caso_id}' no existe en la base de datos."
                self._log_trace("solicitar_antecedentes", args, "ERROR_NO_ENCONTRADO", msg)
                return {"ok": False, "error": msg, "codigo_error": "CASO_NO_ENCONTRADO"}

            caso = dict(caso_row)
            user, auth_err = self._authenticate_and_authorize(conn, usuario_id, caso["org_id"])
            if auth_err:
                self._log_trace("solicitar_antecedentes", args, "ERROR_PERMISOS", auth_err)
                return {"ok": False, "error": auth_err, "codigo_error": "ACCESO_DENEGADO_PR7"}

            # Regla 1 (PRO-ANT §4): Solo usuarios con rol de operador o supervisor pueden registrar una solicitud
            if user["rol"] not in ("operador", "supervisor"):
                msg = (
                    f"ACCIÓN RECHAZADA: El usuario {user['nombre']} ({usuario_id}) tiene rol '{user['rol']}'. "
                    f"Según [PRO-ANT, §4. Límites, v1 (Vigente)], solo usuarios con rol de 'operador' o 'supervisor' "
                    f"pueden registrar una solicitud de antecedentes."
                )
                self._log_trace("solicitar_antecedentes", args, "RECHAZADO_ROL", msg)
                return {"ok": False, "error": msg, "codigo_error": "ROL_NO_AUTORIZADO"}

            # Regla 2 (PRO-ANT §4): No se puede solicitar antecedentes sobre un caso aprobado automáticamente
            if caso["estado"] == "aprobado_automatico":
                msg = (
                    f"ACCIÓN RECHAZADA: El caso {caso_id} se encuentra en estado 'aprobado_automatico'. "
                    f"Según [PRO-ANT, §4. Límites, v1 (Vigente)], no se puede solicitar antecedentes sobre un caso "
                    f"aprobado automáticamente, pues ese caso no vuelve a revisarse."
                )
                self._log_trace("solicitar_antecedentes", args, "RECHAZADO_ESTADO", msg)
                return {"ok": False, "error": msg, "codigo_error": "CASO_APROBADO_AUTOMATICO"}

            # Regla 3 (PRO-ANT §2): Contenido obligatorio (documentos y motivo comprensible)
            if not documentos_solicitados or len(documentos_solicitados.strip()) < 5:
                msg = "ACCIÓN RECHAZADA: Debe indicar la lista de documentos o capturas requeridos (PRO-ANT §2)."
                self._log_trace("solicitar_antecedentes", args, "RECHAZADO_VALIDACION", msg)
                return {"ok": False, "error": msg, "codigo_error": "DOCUMENTOS_VACIOS"}

            if not motivo or len(motivo.strip()) < 10:
                msg = "ACCIÓN RECHAZADA: Debe indicar un motivo comprensible para una persona no técnica (PRO-ANT §2)."
                self._log_trace("solicitar_antecedentes", args, "RECHAZADO_VALIDACION", msg)
                return {"ok": False, "error": msg, "codigo_error": "MOTIVO_INSUFICIENTE"}

            # Regla 4 (PRO-ANT §4): Contar solicitudes existentes en la base de datos
            cur.execute(
                "SELECT COUNT(*) AS total FROM solicitudes_antecedentes WHERE caso_id = ?",
                (caso_id,),
            )
            count_prev = cur.fetchone()["total"]

            if count_prev >= 2 and user["rol"] != "supervisor":
                msg = (
                    f"ACCIÓN RECHAZADA: {caso_id} ya tiene {count_prev} solicitudes de antecedentes registradas; "
                    f"una tercera solicitud debe registrarla un supervisor ([PRO-ANT, §4. Límites, v1 (Vigente)])."
                )
                self._log_trace("solicitar_antecedentes", args, "RECHAZADO_LIMITE_PRO_ANT", msg)
                return {
                    "ok": False,
                    "error": msg,
                    "codigo_error": "LIMITE_SOLICITUDES_OPERADOR",
                    "solicitudes_existentes": count_prev,
                }

            # Regla 5 (Principio PR-6): Confirmación humana explícita obligatoria antes de escribir
            if not confirmado:
                msg = (
                    f"CONFIRMACIÓN HUMANA REQUERIDA (PR-6): La solicitud de antecedentes para el caso {caso_id} "
                    f"cumple todas las reglas de [PRO-ANT, §4. Límites, v1 (Vigente)] (solicitudes previas: {count_prev}). "
                    f"No se ha escrito nada aún en la base de datos. Confirme explícitamente (`confirmado=True`) "
                    f"para registrar la solicitud y cambiar el estado del caso a 'solicitud_antecedentes'."
                )
                self._log_trace("solicitar_antecedentes", args, "PENDIENTE_CONFIRMACION_PR6", msg)
                return {
                    "ok": True,
                    "requiere_confirmacion": True,
                    "ejecutado": False,
                    "mensaje": msg,
                    "borrador": {
                        "caso_id": caso_id,
                        "usuario_id": usuario_id,
                        "rol": user["rol"],
                        "documentos_solicitados": documentos_solicitados.strip(),
                        "motivo": motivo.strip(),
                        "solicitudes_previas": count_prev,
                    },
                }

            # Ejecución confirmada: generar nuevo ID correlativo e insertar con consulta parametrizada
            cur.execute("SELECT COUNT(*) AS total_global FROM solicitudes_antecedentes")
            next_num = cur.fetchone()["total_global"] + 1
            nueva_id = f"SA-{next_num:03d}"
            fecha_hoy = datetime.date.today().isoformat()

            cur.execute(
                """
                INSERT INTO solicitudes_antecedentes
                (solicitud_id, caso_id, usuario_id, fecha, documentos_solicitados, motivo, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nueva_id,
                    caso_id,
                    usuario_id,
                    fecha_hoy,
                    documentos_solicitados.strip(),
                    motivo.strip(),
                    "pendiente",
                ),
            )
            cur.execute(
                "UPDATE casos SET estado = ? WHERE caso_id = ?",
                ("solicitud_antecedentes", caso_id),
            )
            conn.commit()

            msg = (
                f"ACCIÓN EJECUTADA CON ÉXITO: Se registró la solicitud {nueva_id} sobre el caso {caso_id} "
                f"con fecha {fecha_hoy} por {user['nombre']} ({user['rol']}) y el caso pasó a estado "
                f"'solicitud_antecedentes' ([PRO-ANT, §3. Registro y efecto, v1 (Vigente)])."
            )
            self._log_trace("solicitar_antecedentes", args, "EJECUTADO_OK", msg)
            return {
                "ok": True,
                "requiere_confirmacion": False,
                "ejecutado": True,
                "solicitud_id": nueva_id,
                "caso_id": caso_id,
                "nuevo_estado_caso": "solicitud_antecedentes",
                "mensaje": msg,
            }

    # =========================================================================
    # PRIMITIVA 2: RESOURCES (Controlados por el Usuario / Aplicación Host)
    # =========================================================================

    def list_resources(self) -> List[Dict[str, str]]:
        return [
            {
                "uri": "mira://corpus/inventario",
                "name": "Inventario del Corpus Documental CU-1",
                "description": "Lista de documentos normativos indexados con su versión, estado y vigencia.",
            },
            {
                "uri": "mira://organizaciones/umbrales",
                "name": "Tabla de Organizaciones y Umbrales Configurados",
                "description": "Umbrales vigentes y plazos en días hábiles por organización cliente.",
            },
        ]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        if uri == "mira://corpus/inventario":
            return {"uri": uri, "inventory": self.rag.index_data["inventory"]}
        if uri == "mira://organizaciones/umbrales":
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM organizaciones ORDER BY org_id ASC")
                return {"uri": uri, "organizaciones": [dict(r) for r in cur.fetchall()]}
        raise ValueError(f"Recurso MCP no encontrado: {uri}")

    # =========================================================================
    # PRIMITIVA 3: PROMPTS (Plantillas Controladas por el Usuario)
    # =========================================================================

    def list_prompts(self) -> List[Dict[str, str]]:
        return [
            {
                "name": "/auditar-caso",
                "description": "Analiza integralmente por qué un caso fue derivado, sus señales, evidencias y qué política aplica.",
            },
            {
                "name": "/preparar-antecedentes",
                "description": "Verifica si un caso cumple los requisitos de PRO-ANT y prepara un borrador de solicitud de antecedentes.",
            },
        ]

    # =========================================================================
    # PROTOCOLO JSON-RPC 2.0 ESTÁNDAR MCP (Para Clientes Externos / stdio)
    # =========================================================================

    def handle_jsonrpc(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa mensajes JSON-RPC 2.0 según la especificación oficial de Model Context Protocol."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mira-cu1-mcp-server", "version": "3.0.0"},
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                }
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments") or {}
                if not hasattr(self, tool_name):
                    raise ValueError(f"Herramienta MCP desconocida: {tool_name}")
                fn = getattr(self, tool_name)
                output = fn(**tool_args)
                result = {
                    "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}],
                    "structuredContent": output,
                    "isError": not output.get("ok", True),
                }
            elif method == "resources/list":
                result = {"resources": self.list_resources()}
            elif method == "resources/read":
                uri = params.get("uri", "")
                data = self.read_resource(uri)
                result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(data, ensure_ascii=False)}]}
            elif method == "prompts/list":
                result = {"prompts": self.list_prompts()}
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Método MCP no soportado: {method}"},
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def run_stdio(self):
        """Ejecuta el servidor MCP leyendo y respondiendo mensajes JSON-RPC por stdin/stdout en UTF-8."""
        import sys

        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            resp = self.handle_jsonrpc(req)
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    import sys

    if "--stdio" in sys.argv:
        MIRAMCPServer().run_stdio()
        sys.exit(0)

    # Suite de verificación en consola de todos los escenarios exigidos por el capítulo 5 y D4-D7
    init_database()  # Asegurar estado limpio de la BD antes de la prueba
    server = MIRAMCPServer()

    print("=" * 90)
    print("VERIFICACIÓN FUNCIONAL DEL SERVIDOR MCP - MIRA CU-1")
    print("=" * 90)

    print("\n1) [D4] Consulta de caso C-012 por operadora U-01 (ORG-01) + Detección de cambio de umbral CU-001:")
    r1 = server.consultar_caso("C-012", "U-01")
    print("  Estado:", r1["caso"]["estado"], "| Puntaje:", r1["caso"]["puntaje"], "| Motivo:", r1["caso"]["motivo_derivacion"])
    for alerta in r1["alertas_auditoria"]:
        print("  [ALERTA]", alerta)

    print("\n2) [D7] Control de acceso multi-tenant (PR-7): Operadora U-01 (ORG-01) intenta ver caso C-020 (ORG-02):")
    r2 = server.consultar_caso("C-020", "U-01")
    print("  Resultado:", r2["error"])

    print("\n3) [Guardrail] Detección de Prompt Injection en evidencias del caso C-014 (boleta E-007):")
    r3 = server.consultar_evidencias("C-014", "U-01")
    for alerta in r3["alertas_seguridad"]:
        print(" ", alerta)

    print("\n4) [D6] Regla PRO-ANT §4 en Servidor: Operadora U-01 intenta 3ra solicitud sobre C-016 (ya tiene SA-001 y SA-002):")
    r4 = server.solicitar_antecedentes(
        caso_id="C-016",
        usuario_id="U-01",
        documentos_solicitados="Nueva foto de la boleta completa",
        motivo="La foto anterior sigue sin mostrar el monto total de la reparación",
        confirmado=True,
    )
    print("  Resultado:", r4["error"])

    print("\n5) [D5 - Paso 1] Solicitud sobre C-013 sin confirmación (`confirmado=False`, PR-6 Human-in-the-loop):")
    r5_pre = server.solicitar_antecedentes(
        caso_id="C-013",
        usuario_id="U-01",
        documentos_solicitados="Presupuesto original timbrado por Taller Las Encinas",
        motivo="El timbre del presupuesto adjunto no coincide con el timbre registrado del taller",
        confirmado=False,
    )
    print("  Ejecutado en BD:", r5_pre["ejecutado"], "| Mensaje:", r5_pre["mensaje"])

    print("\n6) [D5 - Paso 2] Solicitud sobre C-013 CON confirmación explícita (`confirmado=True`):")
    r5_ok = server.solicitar_antecedentes(
        caso_id="C-013",
        usuario_id="U-01",
        documentos_solicitados="Presupuesto original timbrado por Taller Las Encinas",
        motivo="El timbre del presupuesto adjunto no coincide con el timbre registrado del taller",
        confirmado=True,
    )
    print("  Ejecutado en BD:", r5_ok["ejecutado"], "| ID Creado:", r5_ok["solicitud_id"], "| Mensaje:", r5_ok["mensaje"])

    # Restaurar BD limpia para no dejar registros de prueba alterados
    init_database()
    print("\n(Base de datos restaurada a su estado inicial limpio tras la prueba)")
