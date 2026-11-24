"""Orquestador: ejecuta el pipeline completo de punta a punta.

    python pipeline/run.py                 # ingesta + reconstrucción + controles + exportes + reporte
    python pipeline/run.py --corte "2026-11-30 23:59:59"   # forzar otra fecha de corte (por defecto: último día cargado)

Es seguro ejecutarlo cuantas veces se quiera: la ingesta omite archivos ya
cargados y las capas core/mart se reconstruyen completas desde staging.
"""
import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
import cobertura  # noqa: E402
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
    # Todo el análisis usa la base completa hasta el corte; ya no hay una foto separada.
    con.execute("DROP SCHEMA IF EXISTS base CASCADE")
    cobertura.construir(con, inicio, corte)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", default=config.FECHA_CORTE,
                    help="fecha de corte; por defecto, el último día con datos cargados")
    ap.add_argument("--inicio", default=config.INICIO_OBSERVACION)
    ap.add_argument("--sin-reporte", action="store_true", help="omite gráficos, diccionario y app")
    args = ap.parse_args()

    for d in (config.RAW_DIR, config.DB_PATH.parent, config.EXPORT_DIR, config.REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    ingest()
    con = duckdb.connect(str(config.DB_PATH))
    corte = args.corte or f"{cobertura.ultimo_dia(con)} 23:59:59"
    print(f"[ok] corte: {corte}")
    construir(con, corte, args.inicio)
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
