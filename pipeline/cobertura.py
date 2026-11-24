"""Cobertura por día y fuente según el periodo real de cada archivo cargado.

Un archivo puede cubrir un día (export diario) o un rango (export mensual o por fechas).
Para cada día y fuente:
  - completo: los archivos de esa fuente cubren de 01:00 a 23:00;
  - parcial:  algún archivo toca el día pero no lo cubre entero (vistas de lista con máximo de filas);
  - falta:    ningún archivo de esa fuente toca el día.

El análisis usa esta tabla para que los promedios diarios, las comparaciones mensuales y las
tendencias se calculen solo con días completos de cada fuente.
"""
import datetime as dt

import pandas as pd

FUENTES = ["registros", "recargas", "apuestas", "casino", "retiros"]
MARGEN = pd.Timedelta(hours=1)  # tolerancia entre archivos consecutivos y en los bordes del día


def tramos(manifiesto: pd.DataFrame) -> dict:
    """Une los periodos de los archivos de cada fuente en tramos continuos."""
    out = {}
    for f in FUENTES:
        iv = sorted((r.periodo_min, r.periodo_max) for r in manifiesto.itertuples() if r.fuente == f)
        merged = []
        for a, b in iv:
            if merged and a <= merged[-1][1] + MARGEN:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out[f] = merged
    return out


def calcular(manifiesto: pd.DataFrame, inicio, fin) -> pd.DataFrame:
    tr = tramos(manifiesto)
    filas = []
    for d in pd.date_range(pd.Timestamp(inicio).normalize(), pd.Timestamp(fin).normalize()):
        for f in FUENTES:
            estado = "falta"
            for a, b in tr[f]:
                if a <= d + MARGEN and b >= d + pd.Timedelta(hours=23):
                    estado = "completo"
                    break
                if a < d + pd.Timedelta(days=1) and b >= d:
                    estado = "parcial"
            filas.append((d.date(), f, estado))
    return pd.DataFrame(filas, columns=["dia", "fuente", "estado"])


def construir(con, inicio, fin):
    man = con.execute("""SELECT fuente, periodo_min, periodo_max FROM meta.manifiesto
                         WHERE estado = 'cargado' AND periodo_min IS NOT NULL""").df()
    cob = calcular(man, inicio, fin)
    con.register("cob_df", cob)
    con.execute("CREATE OR REPLACE TABLE meta.cobertura_dia AS SELECT dia::DATE dia, fuente, estado FROM cob_df")
    con.unregister("cob_df")
    resumen = cob.groupby("estado").size().to_dict()
    print(f"[ok] cobertura por día: {resumen}")


def ultimo_dia(con) -> dt.date:
    """Último día con datos cargados (fin del periodo más reciente)."""
    return con.execute("SELECT max(periodo_max)::DATE FROM meta.manifiesto WHERE estado = 'cargado'").fetchall()[0][0]
