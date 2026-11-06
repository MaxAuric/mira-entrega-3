"""
Demostración de Cliente MCP Externo Independiente (Rúbrica P2 - Paso 'Cliente Externo').
Lanza el Servidor MCP (`python -m src.mcp_server.server --stdio`) como un subproceso aislado
y se comunica con él exclusivamente mediante mensajes JSON-RPC 2.0 sobre stdin/stdout
(el estándar de transporte de Model Context Protocol visto en clases).

Demuestra que:
1. Cualquier cliente externo puede descubrir las primitivas (`initialize`, `tools/list`, `resources/list`).
2. Las validaciones y reglas de negocio (`PRO-ANT §4` y `PR-7`) están impuestas en el servidor MCP
   y no dependen de nuestra interfaz web.
"""

import json
import subprocess
import sys


def send_rpc(proc: subprocess.Popen, msg: dict) -> dict:
    line = json.dumps(msg, ensure_ascii=False) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()
    resp_line = proc.stdout.readline()
    return json.loads(resp_line)


def run_external_client_demo():
    import os

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.mcp_server.server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )

    try:
        print("=" * 90)
        print("DEMO DE CLIENTE MCP EXTERNO (Transporte Estándar JSON-RPC 2.0 sobre stdio)")
        print("=" * 90)

        # 1. Handshake initialize
        r_init = send_rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        print("\n1) Handshake MCP `initialize`:")
        print("   Servidor conectado:", r_init["result"]["serverInfo"])

        # 2. Descubrimiento de herramientas (tools/list)
        r_tools = send_rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_names = [t["name"] for t in r_tools["result"]["tools"]]
        print("\n2) Descubrimiento `tools/list`:")
        print("   Herramientas expuestas:", tool_names)

        # 3. Llamada a herramienta de lectura desde cliente externo (tools/call -> consultar_caso)
        r_call1 = send_rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "consultar_caso", "arguments": {"caso_id": "C-015", "usuario_id": "U-01"}},
            },
        )
        caso_data = r_call1["result"]["structuredContent"]["caso"]
        print("\n3) Invocación `tools/call` -> `consultar_caso(C-015, U-01)`:")
        print(f"   Caso: {caso_data['caso_id']} | Puntaje: {caso_data['puntaje']} | Motivo: {caso_data['motivo_derivacion']}")

        # 4. Prueba de que el cliente externo NO puede saltarse la regla PRO-ANT §4 en C-016
        r_call2 = send_rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "solicitar_antecedentes",
                    "arguments": {
                        "caso_id": "C-016",
                        "usuario_id": "U-01",
                        "documentos_solicitados": "Intento desde cliente externo",
                        "motivo": "Intento de saltarse la interfaz web llamando directo al servidor MCP",
                        "confirmado": True,
                    },
                },
            },
        )
        err_data = r_call2["result"]["structuredContent"]
        print("\n4) Intento de bypass desde Cliente Externo (`solicitar_antecedentes` en C-016 con confirmado=True):")
        print(f"   isError={r_call2['result']['isError']} | Respuesta del Servidor: {err_data['error']}")
        print("=" * 90)
    finally:
        proc.terminate()


if __name__ == "__main__":
    run_external_client_demo()

