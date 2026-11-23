"""Orquestador: ejecuta el pipeline completo de punta a punta.

    python pipeline/run.py                 # ingesta + reconstrucción + controles + exportes + reporte
    python pipeline/run.py --corte "2026-11-30 23:59:59"   # recalcular a otra fecha de corte

Es seguro ejecutarlo cuantas veces se quiera: la ingesta omite archivos ya
cargados y las capas core/mart se reconstruyen completas desde staging.
"""
import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from controles import ejecutar_controles  # noqa: E402
from exportar import exportar  # noqa: E402
from ingest import ingest  # noqa: E402
from sms_check import main as verificar_sms  # noqa: E402

PASOS_SQL = ["10_core.sql", "20_mart.sql", "30_segmentos.sql", "40_audiencias.sql"]


def construir(con, corte, inicio):
    con.execute(f"SET VARIABLE corte = TIMESTAMP '{corte}'")
    con.execute(f"SET VARIABLE inicio = TIMESTAMP '{inicio}'")
    con.execute(f"SET VARIABLE version = '{config.VERSION_REGLAS}'")
    con.execute(f"SET VARIABLE semilla = '{config.SEMILLA_CONTROL}'")
    for archivo in PASOS_SQL:
        con.execute((config.SQL_DIR / archivo).read_text(encoding="utf-8"))
        print(f"[ok] {archivo}")
    # Foto base del análisis (último mes completo) en el esquema "base": mismas reglas, otra fecha.
    fin = min(config.FIN_ANALISIS, corte)
    con.execute(f"SET VARIABLE fin_analisis = TIMESTAMP '{fin}'")
    con.execute(f"SET VARIABLE corte = TIMESTAMP '{fin}'")
    for archivo in ["20_mart.sql", "30_segmentos.sql"]:
        sql = (config.SQL_DIR / archivo).read_text(encoding="utf-8").replace("mart.", "base.").replace("SCHEMA IF NOT EXISTS mart", "SCHEMA IF NOT EXISTS base")
        con.execute("CREATE SCHEMA IF NOT EXISTS base")
        con.execute(sql)
    con.execute(f"SET VARIABLE corte = TIMESTAMP '{corte}'")
    print(f"[ok] foto base del análisis al {fin}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", default=config.FECHA_CORTE)
    ap.add_argument("--inicio", default=config.INICIO_OBSERVACION)
    ap.add_argument("--sin-reporte", action="store_true", help="omite gráficos, diccionario y app")
    args = ap.parse_args()

    for d in (config.RAW_DIR, config.DB_PATH.parent, config.EXPORT_DIR, config.REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    ingest()
    con = duckdb.connect(str(config.DB_PATH))
    construir(con, args.corte, args.inicio)
    fallas = ejecutar_controles(con)
    exportar(con)
    verificar_sms()
    if not args.sin_reporte:
        from analisis import generar_reporte
        generar_reporte(con)
    con.close()
    if not args.sin_reporte:
        import diccionario
        import informe
        diccionario.main()
        informe.main()
    if fallas:
        print(f"\nATENCIÓN: {fallas} control(es) fallaron. Revisar reports/controles.csv antes de usar audiencias.")
        sys.exit(1)
    print("\nPipeline completado sin fallas de control.")


if __name__ == "__main__":
    main()
