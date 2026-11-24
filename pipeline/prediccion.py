"""Modelos predictivos (regresión logística) sobre toda la base.

Dos modelos, reentrenados en cada carga:
  - abandono:   de los jugadores activos (recarga o apuesta en los últimos 30 días), ¿quién no vuelve a
                recargar ni apostar en los próximos 30 días?
  - activacion: de los registrados en los últimos 30 días sin recarga, ¿quién hace su primera recarga
                en los próximos 14 días?

Cómo se entrena sin mirar el futuro:
  1. Se toman cortes simulados semanales. En cada corte T las variables solo usan datos <= T y el
     resultado se mide en (T, T + ventana].
  2. Validación temporal: el modelo se entrena con los cortes cuyo resultado termina antes del último
     corte disponible y se evalúa en ese último corte, que no vio.
  3. El modelo final se entrena con todos los cortes y puntúa a la población al corte real.

No se usan campos de Registros que son una foto del día de la exportación (depositante, saldo, último
login, KYC): filtrarían el futuro. La actividad es recarga o apuesta deportiva; casino aún no tiene
historia suficiente para entrenar (existe desde el 28-oct).

Salidas: mart.prediccion_jugador, mart.prediccion_metricas y reports/prediccion.json (agregados).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from config import REPORT_DIR  # noqa: E402

# Base de actividad: recargas y apuestas deportivas válidas (sin pruebas).
BASE_SQL = """
CREATE OR REPLACE TEMP TABLE p_act AS
  SELECT player_id, fecha_hora f, 'r' src, monto m, NULL::INT live, NULL::VARCHAR tipo, metodo FROM core.recarga WHERE coalesce(es_prueba, 0) = 0
  UNION ALL
  SELECT player_id, fecha_hora, 'a', monto_apostado, live_cod, tipo_apuesta, NULL FROM core.apuesta WHERE coalesce(es_prueba, 0) = 0;
CREATE OR REPLACE TEMP TABLE p_reg AS
  SELECT player_id, fecha_registro, fecha_nacimiento, genero, verificacion_celular_cod, fecha_verificacion_celular,
         fuente_registro_cod, network_id, promocode_registro, telefono_estado
  FROM core.registro WHERE coalesce(es_prueba, 0) = 0;
"""

ABANDONO_SQL = """
WITH t AS (SELECT getvariable('t_pred') t),
     a AS (SELECT p.* FROM p_act p, t WHERE p.f <= t.t),
     prim AS (SELECT player_id, min(f) primera FROM a GROUP BY 1),
     g AS (
       SELECT a.player_id,
              date_diff('day', max(a.f), any_value(t.t)) dias_sin_actividad,
              count(DISTINCT a.f::DATE) FILTER (WHERE a.f > t.t - INTERVAL 30 DAY) dias_activos_30,
              count(DISTINCT a.f::DATE) FILTER (WHERE a.f > t.t - INTERVAL 60 DAY AND a.f <= t.t - INTERVAL 30 DAY) dias_activos_30_60,
              coalesce(sum(a.m) FILTER (WHERE a.src = 'r' AND a.f > t.t - INTERVAL 30 DAY), 0) recargado_30,
              coalesce(sum(a.m) FILTER (WHERE a.src = 'a' AND a.f > t.t - INTERVAL 30 DAY), 0) apostado_30,
              count(*) FILTER (WHERE a.src = 'a' AND a.f > t.t - INTERVAL 60 DAY) apuestas_60,
              count(*) FILTER (WHERE a.src = 'r' AND a.f > t.t - INTERVAL 60 DAY) recargas_60,
              avg((a.live = 1)::INT) FILTER (WHERE a.src = 'a' AND a.f > t.t - INTERVAL 60 DAY) pct_en_vivo,
              median(a.m) FILTER (WHERE a.src = 'a' AND a.f > t.t - INTERVAL 60 DAY) apuesta_mediana,
              mode(a.metodo) FILTER (WHERE a.src = 'r' AND a.f > t.t - INTERVAL 60 DAY) metodo
       FROM a, t GROUP BY 1
       HAVING max(a.f) > any_value(t.t) - INTERVAL 30 DAY),
     y AS (SELECT DISTINCT p.player_id FROM p_act p, t WHERE p.f > t.t AND p.f <= t.t + INTERVAL 30 DAY)
SELECT g.*, (y.player_id IS NULL)::INT y,
       date_diff('day', least(coalesce(r.fecha_registro, prim.primera), prim.primera), t.t) antiguedad_dias,
       (r.player_id IS NOT NULL)::INT registrado_desde_julio,
       (r.verificacion_celular_cod = 30 AND coalesce(r.fecha_verificacion_celular, r.fecha_registro) <= t.t)::INT verificado,
       date_diff('year', r.fecha_nacimiento, t.t) edad
FROM g CROSS JOIN t LEFT JOIN y USING (player_id) LEFT JOIN prim USING (player_id) LEFT JOIN p_reg r USING (player_id)
"""

ACTIVACION_SQL = """
WITH t AS (SELECT getvariable('t_pred') t),
     pob AS (SELECT r.* FROM p_reg r, t
             WHERE r.fecha_registro > t.t - INTERVAL 30 DAY AND r.fecha_registro <= t.t
               AND r.fecha_registro >= getvariable('inicio_obs')
               AND NOT EXISTS (SELECT 1 FROM p_act p WHERE p.player_id = r.player_id AND p.src = 'r' AND p.f <= t.t)),
     apu AS (SELECT player_id, count(*) n FROM p_act, t WHERE src = 'a' AND f <= t.t GROUP BY 1),
     y AS (SELECT DISTINCT p.player_id FROM p_act p, t WHERE p.src = 'r' AND p.f > t.t AND p.f <= t.t + INTERVAL 14 DAY)
SELECT pob.player_id, (y.player_id IS NOT NULL)::INT y,
       date_diff('day', pob.fecha_registro, t.t) dias_desde_registro,
       hour(pob.fecha_registro) hora_registro,
       (isodow(pob.fecha_registro) >= 6)::INT registro_fin_de_semana,
       (pob.verificacion_celular_cod = 30 AND coalesce(pob.fecha_verificacion_celular, pob.fecha_registro) <= t.t)::INT verificado,
       date_diff('year', pob.fecha_nacimiento, t.t) edad,
       coalesce(pob.genero, 'NA') genero,
       coalesce(pob.fuente_registro_cod::VARCHAR, 'NA') fuente_registro,
       coalesce(pob.network_id::VARCHAR, 'NA') red,
       (pob.promocode_registro IS NOT NULL AND pob.promocode_registro <> '')::INT con_promocode,
       (pob.telefono_estado = 'valido')::INT telefono_valido,
       (coalesce(apu.n, 0) > 0)::INT aposto_sin_recargar
FROM pob CROSS JOIN t LEFT JOIN y USING (player_id) LEFT JOIN apu USING (player_id)
"""

MODELOS = {
    "abandono": dict(
        sql=ABANDONO_SQL, ventana=30, paso=7, historia=60,
        num=["dias_sin_actividad", "dias_activos_30", "tendencia", "log_recargado_30", "log_apostado_30",
             "pct_en_vivo", "log_apuesta_mediana", "solo_recarga", "antiguedad_dias", "registrado_desde_julio", "verificado", "edad"],
        cat=["metodo"],
        etiquetas={
            "dias_sin_actividad": ("días sin recargar ni apostar", "días"),
            "dias_activos_30": ("días con actividad en los últimos 30", "días"),
            "tendencia": ("cambio de días activos frente al mes anterior", "días"),
            "log_recargado_30": ("monto recargado en los últimos 30 días", "$"),
            "log_apostado_30": ("monto apostado en deportes en los últimos 30 días", "$"),
            "pct_en_vivo": ("proporción de apuestas en vivo", "%"),
            "log_apuesta_mediana": ("apuesta típica", "$"),
            "solo_recarga": ("recarga sin apostar en deportes", "sí/no"),
            "antiguedad_dias": ("antigüedad como jugador", "días"),
            "registrado_desde_julio": ("registrado desde julio", "sí/no"),
            "verificado": ("celular verificado", "sí/no"),
            "edad": ("edad", "años"),
        }),
    "activacion": dict(
        sql=ACTIVACION_SQL, ventana=14, paso=7, historia=30,
        num=["dias_desde_registro", "verificado", "edad", "con_promocode", "telefono_valido", "aposto_sin_recargar",
             "registro_fin_de_semana", "hora_registro"],
        cat=["genero", "fuente_registro", "red"],
        etiquetas={
            "dias_desde_registro": ("días desde el registro sin recargar", "días"),
            "verificado": ("celular verificado", "sí/no"),
            "edad": ("edad", "años"),
            "con_promocode": ("se registró con código promocional", "sí/no"),
            "telefono_valido": ("teléfono válido", "sí/no"),
            "aposto_sin_recargar": ("apostó sin haber recargado", "sí/no"),
            "registro_fin_de_semana": ("se registró en fin de semana", "sí/no"),
            "hora_registro": ("hora del registro", "h"),
        }),
}


def preparar(df, modelo):
    df = df.copy()
    if modelo == "abandono":
        df["tendencia"] = df.dias_activos_30 - df.dias_activos_30_60
        for c in ["recargado_30", "apostado_30", "apuesta_mediana"]:
            df["log_" + c] = np.log1p(df[c].fillna(0).astype(float))
        df["solo_recarga"] = ((df.recargas_60 > 0) & (df.apuestas_60 == 0)).astype(int)
        df["pct_en_vivo"] = df.pct_en_vivo.fillna(0)
        top = ["YAJUEGO PAGOS", "MOVII PSE", "MOVII BREB", "ASTROPAY"]
        df["metodo"] = df.metodo.where(df.metodo.isin(top), np.where(df.metodo.isna(), "sin recarga", "otro"))
    df["edad"] = df.edad.where(df.edad.between(18, 90))
    return df


def construir_pipeline(num, cat):
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", __import__("sklearn.impute", fromlist=["SimpleImputer"]).SimpleImputer(strategy="median")),
                          ("esc", StandardScaler())]), num),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=0.01), cat),
    ])
    return Pipeline([("pre", pre), ("lr", LogisticRegression(max_iter=2000, C=1.0))])


def datos_corte(con, sql, t):
    con.execute(f"SET VARIABLE t_pred = TIMESTAMP '{t}'")
    return con.execute(sql).df()


def factores(pipe, X, cfg):
    """Efecto de cada variable en palabras: cuánto cambia la probabilidad al pasar del percentil 25 al 75."""
    num = cfg["num"]
    sc = pipe.named_steps["pre"].named_transformers_["num"].named_steps["esc"]
    coefs = pipe.named_steps["lr"].coef_[0][:len(num)]
    out = []
    for c, b, sd in zip(num, coefs, sc.scale_):
        x = X[c].dropna().astype(float)
        binaria = set(x.unique()) <= {0, 1}
        lo, hi = (0.0, 1.0) if binaria else (float(x.quantile(0.25)), float(x.quantile(0.75)))
        if hi == lo:
            continue
        orr = math.exp(b / sd * (hi - lo)) if sd else 1.0
        nombre, unidad = cfg["etiquetas"][c]
        if c.startswith("log_"):
            lo, hi = math.expm1(lo), math.expm1(hi)
        out.append(dict(variable=c, nombre=nombre, unidad=unidad, binaria=binaria, desde=lo, hasta=hi, odds=orr))
    return sorted(out, key=lambda r: -abs(math.log(r["odds"])))


def calibracion(y, p, grupos=10):
    d = pd.DataFrame({"y": y, "p": p})
    d["g"] = pd.qcut(d.p.rank(method="first"), grupos, labels=False)
    c = d.groupby("g").agg(pred=("p", "mean"), real=("y", "mean"), n=("y", "size")).reset_index()
    return c.to_dict(orient="records")


def ajustar_nivel(pipe, X, y):
    """Corrige el intercepto para que la probabilidad promedio iguale la tasa observada en el periodo más
    reciente. El orden de los jugadores no cambia; solo el nivel (la base cambia de un mes a otro)."""
    lr = pipe.named_steps["lr"]
    z = pipe.named_steps["pre"].transform(X) @ lr.coef_[0] + lr.intercept_[0]
    obj, lo, hi = float(np.mean(y)), -5.0, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if np.mean(1 / (1 + np.exp(-(z + mid)))) < obj:
            lo = mid
        else:
            hi = mid
    lr.intercept_ = lr.intercept_ + (lo + hi) / 2
    return (lo + hi) / 2


def entrenar(con, nombre, cfg, corte, inicio):
    corte, inicio = pd.Timestamp(corte), pd.Timestamp(inicio)
    ultimo_t = corte - pd.Timedelta(days=cfg["ventana"])
    cortes = []
    t = ultimo_t
    while t >= inicio + pd.Timedelta(days=cfg["historia"]):
        cortes.append(t)
        t -= pd.Timedelta(days=cfg["paso"])
    cortes = sorted(cortes)
    frames = []
    for t in cortes:
        df = preparar(datos_corte(con, cfg["sql"], t), nombre)
        df["t"] = t
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    cols = cfg["num"] + cfg["cat"]
    # Validación temporal: entrenar con cortes cuyo resultado se cierra antes del último corte; evaluar en el último.
    t_val = cortes[-1]
    tr = data[data.t + pd.Timedelta(days=cfg["ventana"]) <= t_val]
    va = data[data.t == t_val]
    pipe = construir_pipeline(cfg["num"], cfg["cat"]).fit(tr[cols], tr.y)
    p = pipe.predict_proba(va[cols])[:, 1]
    orden = np.argsort(-p)
    top = orden[: max(1, int(len(p) * 0.2))]
    met = dict(modelo=nombre, n_entrenamiento=int(len(tr)), n_validacion=int(len(va)), cortes=len(cortes),
               t_validacion=str(t_val.date()), ventana_dias=cfg["ventana"],
               auc=float(roc_auc_score(va.y, p)), brier=float(brier_score_loss(va.y, p)),
               tasa_real=float(va.y.mean()), tasa_predicha=float(p.mean()),
               captura_top20=float(va.y.values[top].sum() / max(va.y.sum(), 1)),
               tasa_top20=float(va.y.values[top].mean()))
    met["calibracion"] = calibracion(va.y.values, p)
    # Modelo final con todos los cortes.
    final = construir_pipeline(cfg["num"], cfg["cat"]).fit(data[cols], data.y)
    met["factores"] = factores(final, data, cfg)
    met["ajuste_nivel"] = float(ajustar_nivel(final, va[cols], va.y))
    # Población actual: mismo SQL al corte real (el resultado aún no existe; la columna y se ignora).
    hoy = preparar(datos_corte(con, cfg["sql"], corte), nombre)
    hoy["probabilidad"] = final.predict_proba(hoy[cols])[:, 1]
    q80, q50 = hoy.probabilidad.quantile(0.8), hoy.probabilidad.quantile(0.5)
    hoy["banda"] = np.where(hoy.probabilidad >= q80, "alta", np.where(hoy.probabilidad >= q50, "media", "baja"))
    hoy["modelo"] = nombre
    return met, hoy[["player_id", "modelo", "probabilidad", "banda"]]


def ejecutar(con, corte, inicio):
    con.execute(f"SET VARIABLE inicio_obs = TIMESTAMP '{inicio}'")
    con.execute(BASE_SQL)
    metricas, scores = [], []
    for nombre, cfg in MODELOS.items():
        met, hoy = entrenar(con, nombre, cfg, corte, inicio)
        metricas.append(met)
        scores.append(hoy)
        print(f"[ok] modelo {nombre}: AUC {met['auc']:.2f} en validación ({met['n_validacion']} jugadores al "
              f"{met['t_validacion']}); el 20 % con mayor probabilidad reúne el {100 * met['captura_top20']:.0f} % de los casos")
    s = pd.concat(scores, ignore_index=True)
    con.register("pred_df", s)
    con.execute("CREATE OR REPLACE TABLE mart.prediccion_jugador AS SELECT * FROM pred_df")
    con.unregister("pred_df")
    plano = pd.DataFrame([{k: v for k, v in m.items() if k not in ("calibracion", "factores")} for m in metricas])
    con.register("met_df", plano)
    con.execute("CREATE OR REPLACE TABLE mart.prediccion_metricas AS SELECT * FROM met_df")
    con.unregister("met_df")
    (REPORT_DIR / "prediccion.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return metricas
