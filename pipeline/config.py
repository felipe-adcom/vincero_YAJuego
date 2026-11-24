"""Parámetros centrales del pipeline YAjuego CRM.

Todo lo que cambia entre ejecuciones (fecha de corte, versión de reglas, semilla
de grupos de control) vive aquí para que cada resultado sea reproducible.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"            # originales, nunca se modifican
DB_PATH = ROOT / "data" / "warehouse" / "yajuego.duckdb"
EXPORT_DIR = ROOT / "data" / "exports"     # salidas con datos personales (no versionadas)
REPORT_DIR = ROOT / "reports"              # salidas agregadas, sin datos personales
SQL_DIR = ROOT / "sql"

# Fecha de corte: último instante que cubren el análisis, los segmentos, las audiencias y los exportes.
FECHA_CORTE = None  # None: el corte es el último día con datos cargados
# Inicio de la ventana observada de transacciones (primer día de las bases).
INICIO_OBSERVACION = "2026-07-01 00:00:00"

# Versión de las reglas de segmentación y campañas. Cambiarla cuando cambie una regla.
VERSION_REGLAS = "v1.0"

# Semilla para asignar grupos de control de forma determinística y repetible.
SEMILLA_CONTROL = "yajuego-sms-2026-10"

# Firma de columnas para reconocer el tipo de archivo por su contenido (no por su nombre).
FIRMAS = {
    "registros": {"ID", "Mobilephone", "Kyc", "Insert Date"},
    "recargas": {"Id", "Client ID", "Amount", "Charge", "Status", "Insert Date"},
    "retiros": {"Id", "Client ID", "Requested Amount", "Net Amount", "Last Update"},
    "apuestas": {"Bet ID", "Client ID", "Stake", "Total Odd", "Status", "Insert Date"},
    "casino": {"Bet Id", "Client Id", "Provider", "Game", "Stake", "Win", "Placed Date"},
}
# Identificador de transacción/registro de cada fuente (para deduplicar y detectar correcciones).
COLUMNA_ID = {"registros": "ID", "recargas": "Id", "retiros": "Id", "apuestas": "Bet ID", "casino": "Bet Id"}
# Un archivo nuevo reemplaza a uno anterior de la misma fuente si su periodo lo contiene
# y comparte al menos esta proporción de identificadores (corrección o re-exportación).
UMBRAL_REEMPLAZO = 0.5
# Columna de fecha que define el periodo real que cubre cada fuente.
COLUMNA_PERIODO = {
    "registros": "Insert Date",
    "recargas": "Insert Date",
    "retiros": "Last Update",   # el export de retiros se corta por fecha de procesamiento
    "apuestas": "Insert Date",
    "casino": "Placed Date",
}
