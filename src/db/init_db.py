"""
Inicializador de Base de Datos SQLite para el Caso MIRA (CU-1: Operador de Revisión).
Carga de forma íntegra las tablas del archivo Excel oficial `data/raw/CU-1_datos.xlsx`
sin modificar ni eliminar ninguno de los registros entregados en el kit (Sección 3.2).
"""

import os
import sqlite3
from pathlib import Path
import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXCEL_PATH = PROJECT_ROOT / "data" / "raw" / "CU-1_datos.xlsx"
DB_PATH = PROJECT_ROOT / "data" / "mira_cu1.db"

SCHEMA_SQL = """
DROP TABLE IF EXISTS cambios_umbral;
DROP TABLE IF EXISTS solicitudes_antecedentes;
DROP TABLE IF EXISTS evidencias;
DROP TABLE IF EXISTS senales;
DROP TABLE IF EXISTS casos;
DROP TABLE IF EXISTS usuarios;
DROP TABLE IF EXISTS organizaciones;

CREATE TABLE organizaciones (
    org_id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    industria TEXT NOT NULL,
    pais TEXT NOT NULL,
    umbral_aprobacion INTEGER NOT NULL,
    umbral_revision INTEGER NOT NULL,
    plazo_resolucion_dias_habiles INTEGER NOT NULL,
    plazo_antecedentes_dias_habiles INTEGER NOT NULL
);

CREATE TABLE usuarios (
    usuario_id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    org_id TEXT NOT NULL,
    rol TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizaciones(org_id)
);

CREATE TABLE casos (
    caso_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    tipo_proceso TEXT NOT NULL,
    fecha_ingreso TEXT NOT NULL,
    estado TEXT NOT NULL,
    puntaje INTEGER NOT NULL,
    decision_sugerida TEXT NOT NULL,
    motivo_derivacion TEXT,
    operador_asignado TEXT,
    vence_el TEXT,
    version_flujo TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizaciones(org_id),
    FOREIGN KEY (operador_asignado) REFERENCES usuarios(usuario_id)
);

CREATE TABLE senales (
    senal_id TEXT PRIMARY KEY,
    caso_id TEXT NOT NULL,
    codigo TEXT NOT NULL,
    valor INTEGER,
    minimo INTEGER,
    bajo_minimo TEXT,
    es_fraude TEXT NOT NULL,
    activa TEXT,
    detalle TEXT,
    FOREIGN KEY (caso_id) REFERENCES casos(caso_id)
);

CREATE TABLE evidencias (
    evidencia_id TEXT PRIMARY KEY,
    caso_id TEXT NOT NULL,
    tipo TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    paginas INTEGER NOT NULL,
    legible TEXT NOT NULL,
    texto_extraido TEXT,
    FOREIGN KEY (caso_id) REFERENCES casos(caso_id)
);

CREATE TABLE solicitudes_antecedentes (
    solicitud_id TEXT PRIMARY KEY,
    caso_id TEXT NOT NULL,
    usuario_id TEXT NOT NULL,
    fecha TEXT NOT NULL,
    documentos_solicitados TEXT NOT NULL,
    motivo TEXT NOT NULL,
    estado TEXT NOT NULL,
    FOREIGN KEY (caso_id) REFERENCES casos(caso_id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(usuario_id)
);

CREATE TABLE cambios_umbral (
    cambio_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    parametro TEXT NOT NULL,
    valor_anterior INTEGER NOT NULL,
    valor_nuevo INTEGER NOT NULL,
    autor TEXT NOT NULL,
    aprobador_1 TEXT,
    aprobador_2 TEXT,
    fecha TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizaciones(org_id)
);
"""

TABLES_ORDER = [
    "organizaciones",
    "usuarios",
    "casos",
    "senales",
    "evidencias",
    "solicitudes_antecedentes",
    "cambios_umbral",
]


def clean_val(val):
    """Normaliza celdas vacías a None y mantiene tipos limpios."""
    if val is None:
        return None
    if isinstance(val, str):
        stripped = val.strip()
        return stripped if stripped != "" else None
    return val


def init_database(excel_path: Path = EXCEL_PATH, db_path: Path = DB_PATH) -> dict:
    """Crea y puebla la base de datos SQLite desde el archivo Excel del kit."""
    if not excel_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo Excel en: {excel_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.load_workbook(excel_path, data_only=True)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.executescript(SCHEMA_SQL)

        counts = {}
        for table in TABLES_ORDER:
            ws = wb[table]
            rows = list(ws.iter_rows(values_only=True))
            headers = [str(h).strip() for h in rows[0] if h is not None]
            placeholders = ", ".join(["?"] * len(headers))
            col_names = ", ".join(headers)
            sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

            inserted = 0
            for row in rows[1:]:
                if not any(row):
                    continue
                values = [clean_val(c) for c in row[: len(headers)]]
                cursor.execute(sql, values)
                inserted += 1
            counts[table] = inserted

        conn.commit()
        return counts
    finally:
        conn.close()


if __name__ == "__main__":
    summary = init_database()
    print(f"Base de datos inicializada exitosamente en: {DB_PATH}")
    for tbl, cnt in summary.items():
        print(f"  - {tbl}: {cnt} registros cargados")

