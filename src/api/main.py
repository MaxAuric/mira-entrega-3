"""
Servidor Backend HTTP/JSON para el Asistente MIRA (CU-1: Operador de Revisión).
Provee los endpoints que consume el Frontend de Joaquín:
- `GET  /health`           : Estado del servidor, del índice RAG y del servidor MCP.
- `GET  /mcp/primitives`   : Lista las Tools, Resources y Prompts expuestos por el servidor MCP.
- `GET  /traces`           : Devuelve el historial de trazas MCP registradas (PR-5).
- `POST /chat`             : Procesa una pregunta o solicitud de acción y retorna respuesta, citas y trazas.
- `POST /confirmar-accion` : Confirma explícitamente una solicitud de antecedentes (`confirmado=True`, PR-6).

Funciona con FastAPI si está instalado, o con el servidor HTTP nativo de Python (`http.server`)
para garantizar que siempre levante sin errores de dependencias externas.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from src.api.agent import MIRAOperadorAgent

agent_instance = MIRAOperadorAgent()

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    app = FastAPI(
        title="MIRA CU-1 · API del Asistente del Operador de Revisión",
        version="3.0.0",
        description="Backend gobernado con RAG + Servidor MCP propio para el Caso de Uso 1 de MIRA.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class ChatRequest(BaseModel):
        pregunta: str
        usuario_id: str = "U-01"
        confirmar_accion: bool = False
        documentos_solicitados: Optional[str] = None
        motivo_solicitud: Optional[str] = None
        simulate_provider_failure: bool = False

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": "v3.0",
            "caso_uso": "CU-1: Asistente del operador de revisión",
            "rag_chunks": agent_instance.mcp.rag.index_data["total_chunks"],
            "mcp_tools": [t["name"] for t in agent_instance.mcp.list_tools()],
        }

    @app.get("/mcp/primitives")
    def mcp_primitives() -> Dict[str, Any]:
        return {
            "tools": agent_instance.mcp.list_tools(),
            "resources": agent_instance.mcp.list_resources(),
            "prompts": agent_instance.mcp.list_prompts(),
        }

    @app.get("/traces")
    def get_traces() -> Dict[str, Any]:
        return {"total": len(agent_instance.mcp.call_traces), "traces": agent_instance.mcp.call_traces}

    @app.post("/chat")
    def chat(req: ChatRequest) -> Dict[str, Any]:
        return agent_instance.process_query(
            pregunta=req.pregunta,
            usuario_id=req.usuario_id,
            confirmar_accion=req.confirmar_accion,
            documentos_solicitados=req.documentos_solicitados,
            motivo_solicitud=req.motivo_solicitud,
            simulate_provider_failure=req.simulate_provider_failure,
        )

except ImportError:
    app = None


class FallbackHTTPHandler(BaseHTTPRequestHandler):
    """Servidor HTTP nativo en caso de ejecutarse sin FastAPI/Uvicorn instalado."""

    def _send_json(self, status_code: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "version": "v3.0",
                    "caso_uso": "CU-1: Asistente del operador de revisión",
                    "rag_chunks": agent_instance.mcp.rag.index_data["total_chunks"],
                    "mcp_tools": [t["name"] for t in agent_instance.mcp.list_tools()],
                },
            )
        elif self.path == "/mcp/primitives":
            self._send_json(
                200,
                {
                    "tools": agent_instance.mcp.list_tools(),
                    "resources": agent_instance.mcp.list_resources(),
                    "prompts": agent_instance.mcp.list_prompts(),
                },
            )
        elif self.path == "/traces":
            self._send_json(
                200,
                {"total": len(agent_instance.mcp.call_traces), "traces": agent_instance.mcp.call_traces},
            )
        else:
            self._send_json(404, {"error": "Ruta no encontrada"})

    def do_POST(self):
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            data = json.loads(raw)
            res = agent_instance.process_query(
                pregunta=data.get("pregunta", ""),
                usuario_id=data.get("usuario_id", "U-01"),
                confirmar_accion=bool(data.get("confirmar_accion", False)),
                documentos_solicitados=data.get("documentos_solicitados"),
                motivo_solicitud=data.get("motivo_solicitud"),
                simulate_provider_failure=bool(data.get("simulate_provider_failure", False)),
            )
            self._send_json(200, res)
        else:
            self._send_json(404, {"error": "Ruta no encontrada"})


def run_server(host: str = "127.0.0.1", port: int = 8000):
    print(f"Servidor Backend MIRA CU-1 iniciado en http://{host}:{port}")
    httpd = HTTPServer((host, port), FallbackHTTPHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()

