"""Ingesta idempotente de archivos originales a la capa de staging.

- Reconoce el tipo de fuente por las columnas del archivo, no por su nombre.
- Calcula el periodo cubierto a partir del contenido.
- Registra cada archivo en `meta.manifiesto` con su hash SHA-256: un archivo ya
  cargado (mismo hash) nunca se vuelve a cargar, aunque tenga otro nombre.
- Corrección de un mes: si un archivo nuevo de la misma fuente contiene el periodo
  de uno anterior y comparte con él al menos UMBRAL_REEMPLAZO de sus identificadores,
  el anterior queda `reemplazado` y deja de alimentar la capa core. Los archivos que
  parten un mes en varias partes (rangos distintos) conviven sin reemplazarse.
- Staging guarda los valores como texto, tal como venían, más trazabilidad
  (archivo, hash, carga, número de fila). Los tipos se asignan en la capa core.
- Cada archivo se carga en una transacción: si el proceso se interrumpe no quedan
  filas a medio cargar.
"""
import datetime as dt
import hashlib
import re
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd
from python_calamine import CalamineWorkbook

from config import COLUMNA_ID, COLUMNA_PERIODO, DB_PATH, FIRMAS, RAW_DIR, UMBRAL_REEMPLAZO


def snake(col: str) -> str:
    col = col.strip().lower().replace(".", "")
    return re.sub(r"[^a-z0-9]+", "_", col).strip("_")


def as_text(v):
    """Convierte una celda a texto sin perder información (enteros sin '.0')."""
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def detectar_fuente(header):
    cols = set(header)
    for fuente, firma in FIRMAS.items():
        if firma <= cols:
            return fuente
    return None


def leer_excel(path: Path):
    wb = CalamineWorkbook.from_path(str(path))
    for nombre in wb.sheet_names:
        filas = wb.get_sheet_by_name(nombre).to_python()
        if not filas:
            continue
        header = [str(h).strip() for h in filas[0]]
        datos = [r for r in filas[1:] if any(v not in (None, "") for v in r)]
        yield nombre, header, datos


def reparar_desplazadas(header, datos):
    """Repara filas de Registros cuya dirección traía comas: el export la partió en varias celdas y corrió
    hacia la derecha las columnas siguientes (código postal, teléfono, fecha de registro...).
    Se detecta porque 'Insert Date' no trae fecha y una de las 3 celdas siguientes sí. La dirección se
    vuelve a unir y el resto de la fila regresa a su columna. Devuelve (datos, filas reparadas)."""
    if "Res Address" not in header or "Insert Date" not in header:
        return datos, 0
    ia, idt = header.index("Res Address"), header.index("Insert Date")
    salida, reparadas = [], 0
    for r in datos:
        r = list(r)
        if not isinstance(r[idt], dt.datetime):
            k = next((j - idt for j in range(idt + 1, min(idt + 4, len(r))) if isinstance(r[j], dt.datetime)), 0)
            if k:
                partes = [str(v).strip() for v in r[ia:ia + k + 1] if v not in (None, "")]
                r = r[:ia] + [", ".join(partes)] + r[ia + k + 1:] + [""] * k
                reparadas += 1
        salida.append(r)
    return salida, reparadas


def init_meta(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute("CREATE SCHEMA IF NOT EXISTS stg")
    con.execute("CREATE SEQUENCE IF NOT EXISTS meta.load_seq START 1")
    con.execute("""
        CREATE TABLE IF NOT EXISTS meta.manifiesto (
            load_id INTEGER, archivo VARCHAR, hoja VARCHAR, sha256 VARCHAR,
            fuente VARCHAR, filas INTEGER, columnas INTEGER,
            periodo_min TIMESTAMP, periodo_max TIMESTAMP, mes_periodo VARCHAR,
            filas_por_mes VARCHAR, cargado_en TIMESTAMP,
            estado VARCHAR,            -- cargado | duplicado_exacto | reemplazado | no_reconocido
            reemplazado_por INTEGER, nota VARCHAR)
    """)


def registrar(con, **kw):
    campos = ["load_id", "archivo", "hoja", "sha256", "fuente", "filas", "columnas", "periodo_min",
              "periodo_max", "mes_periodo", "filas_por_mes", "cargado_en", "estado", "reemplazado_por", "nota"]
    con.execute(f"INSERT INTO meta.manifiesto ({','.join(campos)}) VALUES ({','.join('?' * len(campos))})",
                [kw.get(c) for c in campos])


def cargar_hoja(con, load_id, path, h, hoja, header, datos, ahora):
    fuente = detectar_fuente(header)
    if fuente is None:
        registrar(con, load_id=load_id, archivo=path.name, hoja=hoja, sha256=h, filas=len(datos),
                  columnas=len(header), cargado_en=ahora, estado="no_reconocido",
                  nota="Columnas no coinciden con ninguna fuente conocida: revisar y ampliar FIRMAS.")
        return f"[revisar] {path.name}/{hoja}: fuente no reconocida"

    datos, reparadas = reparar_desplazadas(header, datos)
    cols = [snake(c) for c in header]
    idx_p = header.index(COLUMNA_PERIODO[fuente])
    fechas = [r[idx_p] for r in datos if isinstance(r[idx_p], dt.datetime)]
    meses = Counter(f.strftime("%Y-%m") for f in fechas)
    mes = meses.most_common(1)[0][0] if meses else None
    pmin, pmax = (min(fechas), max(fechas)) if fechas else (None, None)

    tabla = f"stg.{fuente}"
    col_defs = ", ".join(f'"{c}" VARCHAR' for c in cols)
    con.execute(f"CREATE TABLE IF NOT EXISTS {tabla} (_load_id INTEGER, _archivo VARCHAR, _sha256 VARCHAR, _fila INTEGER, {col_defs})")
    existentes = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='stg' AND table_name=?", [fuente]).fetchall()}
    for c in cols:
        if c not in existentes:  # el proveedor agregó una columna: se conserva sin romper cargas previas
            con.execute(f'ALTER TABLE {tabla} ADD COLUMN "{c}" VARCHAR')

    df = pd.DataFrame([[as_text(v) for v in r] for r in datos], columns=cols, dtype="string")
    df.insert(0, "_fila", range(2, len(df) + 2))
    df.insert(0, "_sha256", h)
    df.insert(0, "_archivo", path.name)
    df.insert(0, "_load_id", load_id)
    con.register("df_carga", df)
    collist = ",".join(f'"{c}"' for c in df.columns)
    con.execute(f"INSERT INTO {tabla} ({collist}) SELECT {collist} FROM df_carga")
    con.unregister("df_carga")

    # ¿Este archivo corrige a uno anterior de la misma fuente?
    idc = snake(COLUMNA_ID[fuente])
    reemplazados = []
    candidatos = con.execute(
        """SELECT load_id FROM meta.manifiesto WHERE fuente=? AND estado='cargado'
           AND periodo_min >= ? AND periodo_max <= ?""", [fuente, pmin, pmax]).fetchall()
    for (old,) in candidatos:
        ratio = con.execute(f"""
            SELECT avg(CASE WHEN n."{idc}" IS NOT NULL THEN 1.0 ELSE 0 END)
            FROM (SELECT DISTINCT "{idc}" FROM {tabla} WHERE _load_id=?) o
            LEFT JOIN (SELECT DISTINCT "{idc}" FROM {tabla} WHERE _load_id=?) n USING ("{idc}")""",
                            [old, load_id]).fetchone()[0] or 0
        if ratio >= UMBRAL_REEMPLAZO:
            con.execute("UPDATE meta.manifiesto SET estado='reemplazado', reemplazado_por=?, nota=? WHERE load_id=?",
                        [load_id, f"{ratio:.0%} de sus identificadores reaparecen en la carga {load_id}", old])
            reemplazados.append(old)

    registrar(con, load_id=load_id, archivo=path.name, hoja=hoja, sha256=h, fuente=fuente, filas=len(datos),
              columnas=len(header), periodo_min=pmin, periodo_max=pmax, mes_periodo=mes,
              filas_por_mes=str(dict(sorted(meses.items()))), cargado_en=ahora, estado="cargado",
              nota=(f"{reparadas} filas con la dirección partida en varias celdas; se reunió y se corrigió el corrimiento de columnas."
                    if reparadas else None))
    return (f"[cargado] {path.name}/{hoja} -> {tabla}: {len(datos)} filas, periodo {pmin} a {pmax}"
            + (f" ({reparadas} filas desplazadas reparadas)" if reparadas else "")
            + (f" (reemplaza cargas {reemplazados})" if reemplazados else ""))


def ingest(raw_dir: Path = RAW_DIR, db_path: Path = DB_PATH, verbose=True):
    con = duckdb.connect(str(db_path))
    init_meta(con)
    # Se ignoran los metadatos de macOS (__MACOSX/, ._archivo) y los bloqueos de Excel (~$archivo).
    archivos = sorted(p for p in raw_dir.rglob("*") if p.suffix.lower() in (".xlsx", ".xlsm")
                      and not p.name.startswith(("._", "~$")) and "__MACOSX" not in p.parts)
    for path in archivos:
        h = sha256(path)
        if con.execute("SELECT 1 FROM meta.manifiesto WHERE archivo=? AND sha256=?", [path.name, h]).fetchone():
            continue  # re-ejecución: este archivo ya fue procesado
        previo = con.execute(
            "SELECT load_id, archivo FROM meta.manifiesto WHERE sha256=? AND estado IN ('cargado','reemplazado') LIMIT 1",
            [h]).fetchone()
        load_id = con.execute("SELECT nextval('meta.load_seq')").fetchone()[0]
        ahora = dt.datetime.now().replace(microsecond=0)
        con.execute("BEGIN TRANSACTION")
        try:
            if previo:
                registrar(con, load_id=load_id, archivo=path.name, sha256=h, cargado_en=ahora, estado="duplicado_exacto",
                          nota=f"Contenido idéntico a {previo[1]} (carga {previo[0]}); no se carga.")
                msg = [f"[omitido] {path.name}: duplicado exacto de {previo[1]}"]
            else:
                msg = [cargar_hoja(con, load_id, path, h, hoja, header, datos, ahora)
                       for hoja, header, datos in leer_excel(path)]
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        if verbose:
            print("\n".join(msg))
    con.close()


if __name__ == "__main__":
    ingest()
