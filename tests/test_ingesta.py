"""Pruebas de la ingesta con archivos sintéticos pequeños (sin datos reales).

    python -m pytest tests/        o        python tests/test_ingesta.py
"""
import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from ingest import ingest, reparar_desplazadas  # noqa: E402

HEADER = ["Id", "Client ID", "Surname", "Agent ID", "Network ID", "Test", "Method", "Status",
          "Amount", "Charge", "Insert Date", "Manual", "Promocode"]


def recargas(path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADER)
    for i, (rid, dia, monto) in enumerate(filas):
        ws.append([rid, 1000 + i, "X", 601, 601, 0, "MOVII PSE", "CREDITED", monto, 0,
                   dt.datetime(2026, 7, dia, 10, 0, 0), 0, None])
    wb.save(path)


def estado(db):
    con = duckdb.connect(str(db), read_only=True)
    r = con.execute("SELECT archivo, estado FROM meta.manifiesto ORDER BY load_id").fetchall()
    con.close()
    return dict(r)


def test_ciclo_completo():
    tmp = Path(tempfile.mkdtemp())
    raw, db = tmp / "raw", tmp / "t.duckdb"
    raw.mkdir()
    try:
        # Dos partes del mismo mes con rangos distintos: conviven.
        recargas(raw / "a_parte1.xlsx", [(1, 1, 100), (2, 2, 200)])
        recargas(raw / "b_parte2.xlsx", [(3, 20, 300), (4, 21, 400)])
        ingest(raw, db, verbose=False)
        assert estado(db) == {"a_parte1.xlsx": "cargado", "b_parte2.xlsx": "cargado"}

        # Re-ejecutar no carga nada nuevo.
        ingest(raw, db, verbose=False)
        con = duckdb.connect(str(db), read_only=True)
        assert con.execute("SELECT count(*) FROM stg.recargas").fetchall()[0][0] == 4
        con.close()

        # Mismo contenido con otro nombre: duplicado exacto, no se carga.
        shutil.copy(raw / "a_parte1.xlsx", raw / "c_copia.xlsx")
        ingest(raw, db, verbose=False)
        assert estado(db)["c_copia.xlsx"] == "duplicado_exacto"

        # Corrección del mes completo: reemplaza a ambas partes.
        recargas(raw / "d_julio_corregido.xlsx", [(1, 1, 100), (2, 2, 250), (3, 20, 300), (4, 21, 400)])
        ingest(raw, db, verbose=False)
        e = estado(db)
        assert e["a_parte1.xlsx"] == "reemplazado" and e["b_parte2.xlsx"] == "reemplazado"
        assert e["d_julio_corregido.xlsx"] == "cargado"
    finally:
        shutil.rmtree(tmp)


def test_reparar_direccion_partida():
    h = ["ID", "Res Address", "Res Postcode", "Mobilephone", "Insert Date", "Insert User"]
    f = dt.datetime(2026, 10, 27, 9, 0)
    buena = [1, "Calle 1", "050001", "3001234567", f, 99]
    corrida = [2, "CR 60", " BARRIO X", "050001", "3007654321", f]  # la columna final se perdió por el corrimiento
    datos, n = reparar_desplazadas(h, [buena, corrida])
    assert n == 1 and datos[0] == buena
    assert datos[1][1] == "CR 60, BARRIO X" and datos[1][3] == "3007654321" and datos[1][4] == f


if __name__ == "__main__":
    test_reparar_direccion_partida()
    test_ciclo_completo()
    print("OK")
