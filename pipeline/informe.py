"""Aplicación web Vincero para YAjuego: consola de datos, segmentos y campañas SMS.

Lee la base (solo agregados, sin datos personales) y escribe una aplicación HTML
autocontenida en reports/informe_yajuego.html. Se regenera con cada corte:

    python pipeline/informe.py
"""
import base64
import json
import html
import re
from datetime import time as dt_time
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH, INICIO_OBSERVACION, REPORT_DIR, ROOT  # noqa: E402
from sms_check import analizar  # noqa: E402

ASSETS = ROOT / "reports" / "assets"


# ───────────────────────── formato ─────────────────────────
def n(x, dec=0):
    """Número con separador de miles con punto y decimales con coma."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return "—"
    s = f"{float(x):,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(x, dec=1):
    return f"{n(x, dec)} %"


def cop(x):
    return f"${n(x)}"


def mm(x):
    """Montos grandes en millones de pesos, sin abreviaturas ambiguas."""
    return f"${n(x / 1e6, 0)} millones"


def esc(s):
    return html.escape(str(s))


# ───────────────────────── gráficos SVG ─────────────────────────
def bars_v(cats, series, fmt=lambda v: n(v), w=680, h=260, ymax=None, sub=None, labels=True):
    """Barras verticales agrupadas. series = [(nombre, valores, var_color)]."""
    pl, pr, pt, pb = 44, 12, 34, 46 if sub else 30
    iw, ih = w - pl - pr, h - pt - pb
    vmax = ymax or max(max(v) for _, v, _ in series) * 1.18
    k = len(series)
    gw = iw / len(cats)
    bw = min(46, gw * 0.7 / k)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i in range(5):
        y = pt + ih - ih * i / 4
        out.append(f'<line x1="{pl}" x2="{w - pr}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{pl - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{esc(fmt(vmax * i / 4))}</text>')
    for ci, c in enumerate(cats):
        cx = pl + gw * ci + gw / 2
        x0 = cx - (bw * k + 2 * (k - 1)) / 2
        for si, (name, vals, col) in enumerate(series):
            v = vals[ci]
            bh = ih * v / vmax
            x = x0 + si * (bw + 2)
            y = pt + ih - bh
            out.append(f'<path d="M{x:.1f},{pt + ih:.1f} V{y + 4:.1f} q0,-4 4,-4 H{x + bw - 4:.1f} q4,0 4,4 V{pt + ih:.1f} Z" '
                       f'style="fill:var({col})"><title>{esc(c)} · {esc(name)}: {esc(fmt(v))}</title></path>')
            if labels:
                out.append(f'<text x="{x + bw / 2:.1f}" y="{y - 6:.1f}" class="lbl" text-anchor="middle">{esc(fmt(v))}</text>')
        out.append(f'<text x="{cx:.1f}" y="{pt + ih + 18}" class="ax" text-anchor="middle">{esc(c)}</text>')
        if sub:
            out.append(f'<text x="{cx:.1f}" y="{pt + ih + 33}" class="ax mute" text-anchor="middle">{esc(sub[ci])}</text>')
    out.append("</svg>")
    return legend(series) + "".join(out)


def bars_h(cats, series, fmt=lambda v: n(v), w=680, lab_w=210, row=34, stacked=False, total_lbl=None, pad_r=90):
    k = 1 if stacked else len(series)
    bh = 13 if k > 1 else 18
    h = row * len(cats) + 16
    iw = w - lab_w - pad_r
    if stacked:
        vmax = max(sum(s[1][i] for s in series) for i in range(len(cats)))
    else:
        vmax = max(max(v) for _, v, _ in series)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for ci, c in enumerate(cats):
        y0 = 8 + ci * row
        out.append(f'<text x="{lab_w - 10}" y="{y0 + row / 2 + 1:.1f}" class="ax" text-anchor="end">{esc(c)}</text>')
        xacc = lab_w
        for si, (name, vals, col) in enumerate(series):
            v = vals[ci]
            bw = max(iw * v / vmax, 0.5)
            if stacked:
                y, x = y0 + (row - bh) / 2, xacc
                xacc += bw + (2 if v > 0 else 0)
            else:
                y, x = y0 + (row - k * bh - 2 * (k - 1)) / 2 + si * (bh + 2), lab_w
            r = min(4, bw / 2, bh / 2)
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh}" rx="{r:.1f}" style="fill:var({col})">'
                       f'<title>{esc(c)} · {esc(name)}: {esc(fmt(v))}</title></rect>')
            if not stacked:
                out.append(f'<text x="{x + bw + 5:.1f}" y="{y + bh - 3:.1f}" class="lbl">{esc(fmt(v))}</text>')
        if stacked and total_lbl:
            out.append(f'<text x="{xacc + 6:.1f}" y="{y0 + row / 2 + 4:.1f}" class="lbl">{esc(total_lbl[ci])}</text>')
    out.append("</svg>")
    return legend(series) + "".join(out)


def lines_small(df, cols, titles, w=680, h=150, fmt=lambda v: n(v), sabados=True, tip=lambda d: f"{d:%d-%m}", pl=58):
    """Líneas pequeñas por día (o semana). Un valor vacío corta la línea: no se dibujan días sin datos completos."""
    MES = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    outs = []
    for col, t in zip(cols, titles):
        pr, pt, pb = 12, 12, 24
        iw, ih = w - pl - pr, h - pt - pb
        v = df[col].astype(float).values
        vmax = (np.nanmax(v) if np.isfinite(v).any() else 1) * 1.1
        xs = [pl + iw * i / max(len(v) - 1, 1) for i in range(len(v))]
        ys = [pt + ih - ih * (x / vmax) if np.isfinite(x) else None for x in v]
        o = [f'<div class="sm-title">{esc(t)}</div><svg viewBox="0 0 {w} {h}" class="chart" role="img">']
        for i in range(4):
            y = pt + ih - ih * i / 3
            o.append(f'<line x1="{pl}" x2="{w - pr}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
            o.append(f'<text x="{pl - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{fmt(vmax * i / 3)}</text>')
        tramo = []
        for x, y in list(zip(xs, ys)) + [(None, None)]:
            if y is None:
                if len(tramo) > 1:
                    o.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in tramo)}" class="line"/>')
                tramo = []
            else:
                tramo.append((x, y))
        mes_prev, x_prev = None, -99
        for d, x, y, val in zip(df.dia, xs, ys, v):
            if d.month != mes_prev:
                if x - x_prev >= 45:  # evita etiquetas encimadas
                    o.append(f'<text x="{x:.1f}" y="{h - 6}" class="ax" text-anchor="start">{d.day}-{MES[d.month]}</text>')
                    x_prev = x
                mes_prev = d.month
            if y is None:
                continue
            if sabados and d.isoweekday() == 6:
                o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" class="dot"><title>Sábado {tip(d)}: {fmt(val)}</title></circle>')
            else:
                o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" class="hit"><title>{tip(d)}: {fmt(val)}</title></circle>')
        o.append("</svg>")
        outs.append("".join(o))
    return ('<div class="legend"><span><i class="sw dotsw"></i>sábado</span><span>Los cortes en la línea son días sin archivo completo</span></div>'
            if sabados else "") + "".join(outs)


def heatmap(mat, w=680, h=230):
    pl, pt, pr, pb = 40, 8, 10, 26
    cw, ch = (w - pl - pr) / 24, (h - pt - pb) / 7
    vmax = max(max(r) for r in mat)
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for d in range(7):
        o.append(f'<text x="{pl - 6}" y="{pt + ch * d + ch / 2 + 4:.1f}" class="ax" text-anchor="end">{dias[d]}</text>')
        for hr in range(24):
            v = mat[d][hr]
            step = min(6, int(7 * v / vmax))
            o.append(f'<rect x="{pl + cw * hr + 1:.1f}" y="{pt + ch * d + 1:.1f}" width="{cw - 2:.1f}" height="{ch - 2:.1f}" rx="2" '
                     f'style="fill:var(--q{step})"><title>{dias[d]} {hr}:00 · {n(v)} apuestas/día</title></rect>')
    for hr in range(0, 24, 3):
        o.append(f'<text x="{pl + cw * hr + cw / 2:.1f}" y="{h - 8}" class="ax" text-anchor="middle">{hr}h</text>')
    o.append("</svg>")
    scale = "".join(f'<i style="background:var(--q{i})"></i>' for i in range(7))
    return "".join(o) + f'<div class="scale"><span>menos</span>{scale}<span>más apuestas por día</span></div>'


def lorenz(curvas, w=680, h=280):
    pl, pr, pt, pb = 44, 16, 12, 36
    iw, ih = w - pl - pr, h - pt - pb
    xmax = 30
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i in range(5):
        y = pt + ih - ih * i / 4
        o.append(f'<line x1="{pl}" x2="{w - pr}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        o.append(f'<text x="{pl - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{25 * i} %</text>')
    for xv in range(0, xmax + 1, 5):
        x = pl + iw * xv / xmax
        o.append(f'<text x="{x:.1f}" y="{pt + ih + 16}" class="ax" text-anchor="middle">{xv} %</text>')
    o.append(f'<text x="{pl + iw / 2}" y="{h - 4}" class="ax mute" text-anchor="middle">% de jugadores con actividad, de mayor a menor</text>')
    for name, xs, ys, col, marks in curvas:
        pts = " ".join(f"{pl + iw * x / xmax:.1f},{pt + ih - ih * y / 100:.1f}" for x, y in zip(xs, ys) if x <= xmax)
        o.append(f'<polyline points="{pts}" class="line" style="stroke:var({col})"/>')
        for i, (mx, my) in enumerate(marks):
            cx, cy = pl + iw * mx / xmax, pt + ih - ih * my / 100
            o.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot" style="fill:var({col})"><title>{name}: top {mx} % = {n(my, 1)} %</title></circle>')
            dy = -9 if col == "--s1" else 17
            o.append(f'<text x="{cx + 8:.1f}" y="{cy + dy:.1f}" class="lbl">top {mx} %: {n(my, 0)} %</text>')
    o.append("</svg>")
    return legend([(c[0], None, c[3]) for c in curvas]) + "".join(o)


def legend(series):
    return '<div class="legend">' + "".join(f'<span><i class="sw" style="background:var({c})"></i>{esc(nm)}</span>' for nm, _, c in series) + "</div>"


def table(df, cols, num=(), cls=""):
    th = "".join(f'<th class="{"num" if c in num else ""}">{esc(lbl)}</th>' for c, lbl in cols)
    rows = []
    for r in df.itertuples(index=False):
        d = r._asdict()
        rows.append("<tr>" + "".join(f'<td class="{"num" if c in num else ""}">{d[c]}</td>' for c, _ in cols) + "</tr>")
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def finding(titulo, obs, evid, interp, decision, chart=""):
    return f"""<article class="finding">
  <h3>{titulo}</h3>
  <div class="f-grid">
    <div class="f-txt">
      <dl>
        <dt>Qué observamos</dt><dd>{obs}</dd>
        <dt>Evidencia</dt><dd>{evid}</dd>
        <dt>Posible interpretación</dt><dd>{interp}</dd>
        <dt>Decisión que permite</dt><dd class="dec">{decision}</dd>
      </dl>
    </div>
    {f'<figure class="f-chart">{chart}</figure>' if chart else ''}
  </div>
</article>"""


def mde(p, nt, nc):
    """Efecto mínimo detectable (puntos porcentuales), 80 % de potencia, alfa 5 % bilateral."""
    if nt == 0 or nc == 0:
        return None
    return 100 * 2.8 * math.sqrt(p * (1 - p) * (1 / nt + 1 / nc))


# ───────────────────────── datos ─────────────────────────
def cargar():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    q = lambda s: con.execute(s).df()  # noqa: E731
    v = lambda s: con.execute(s).fetchall()[0][0]  # noqa: E731
    D = {}
    con.execute("SET VARIABLE fin_analisis = (SELECT max(fecha_corte) FROM mart.jugador_resumen)")
    # El análisis describe la ventana hasta el corte; los datos posteriores van al módulo de seguimiento.
    for vista, tabla, col in [("v_recarga", "core.recarga", "fecha_hora"), ("v_apuesta", "core.apuesta", "fecha_hora"),
                    ("v_retiro", "core.retiro", "fecha_ultima_actualizacion"), ("v_registro", "core.registro", "fecha_registro")]:
        con.execute(f"CREATE OR REPLACE TEMP VIEW {vista} AS SELECT * FROM {tabla} WHERE {col} <= getvariable('fin_analisis')")
    D["corte"] = v("SELECT max(fecha_corte) FROM mart.jugador_resumen")
    D["fin_analisis"] = v("SELECT max(fecha_corte) FROM mart.jugador_resumen")
    D["universo_base"] = v("SELECT count(*) FROM mart.jugador_resumen")
    D["manifiesto"] = q("SELECT archivo, fuente, filas, periodo_min, periodo_max, estado FROM meta.manifiesto ORDER BY fuente, periodo_min")
    D["controles"] = q("SELECT estado, count(*) n FROM meta.controles GROUP BY 1")
    D["universo"] = v("SELECT count(*) FROM mart.jugador_resumen")
    D["reg"] = v("SELECT count(*) FROM v_registro")
    D["rec"] = q("SELECT count(*) n, sum(monto) m, count(DISTINCT player_id) j FROM v_recarga").iloc[0]
    D["apu"] = q("SELECT count(*) n, sum(monto_apostado) m, count(DISTINCT player_id) j FROM v_apuesta").iloc[0]
    D["lin"] = v("SELECT count(*) FROM core.apuesta_linea WHERE fecha_hora <= getvariable('fin_analisis')")
    D["ret"] = q("SELECT count(*) n, sum(monto_neto) m, count(DISTINCT player_id) j FROM v_retiro").iloc[0]
    D["cob"] = q("""SELECT en_registros, count(*) j, sum(apu_monto) am, sum(rec_monto) rm,
                    sum((rec_n>0)::INT) cr, sum((apu_n>0)::INT) ca FROM mart.jugador_resumen GROUP BY 1""").set_index("en_registros")
    D["emb"] = pd.read_csv(REPORT_DIR / "tablas" / "02_embudo_cohortes.csv")
    D["t1"] = pd.read_csv(REPORT_DIR / "tablas" / "03_tiempo_primera_recarga.csv")
    D["dia"] = pd.read_csv(REPORT_DIR / "tablas" / "04_actividad_diaria.csv", parse_dates=["dia"])
    D["dia"]["dia"] = D["dia"].dia.dt.date
    D["rec_med"] = v("SELECT median(monto) FROM v_recarga")
    D["intervalo"] = q("""SELECT median(apu_intervalo_mediano_dias) med, quantile_cont(apu_intervalo_mediano_dias, 0.9) p90
                          FROM mart.jugador_resumen WHERE apu_intervalo_mediano_dias IS NOT NULL""").iloc[0]
    D["cop_eur"] = v("SELECT median(TRY_CAST(stake AS DOUBLE) / nullif(TRY_CAST(stake_eur AS DOUBLE), 0)) FROM stg.apuestas")
    D["mes"] = pd.read_csv(REPORT_DIR / "tablas" / "05_comparacion_mensual.csv")
    D["rc"] = pd.read_csv(REPORT_DIR / "tablas" / "06_recencia_contacto.csv")
    D["conc"] = pd.read_csv(REPORT_DIR / "tablas" / "07_concentracion.csv")
    D["lor"] = q(f"SELECT apu_monto, rec_monto FROM mart.jugador_resumen WHERE apu_n>0 OR rec_n>0")
    hm = pd.read_csv(REPORT_DIR / "tablas" / "08_apuestas_dia_hora.csv")
    D["hm"] = hm.pivot(index="dia_semana", columns="hora", values="apuestas_promedio_dia").values.tolist()
    D["dow"] = q("""SELECT isodow(fecha_hora) d, count(*)/count(DISTINCT fecha_hora::DATE) x FROM v_apuesta a
                    JOIN meta.cobertura_dia c ON c.dia = a.fecha_hora::DATE AND c.fuente = 'apuestas' AND c.estado = 'completo'
                    GROUP BY 1 ORDER BY 1""")
    D["mix"] = pd.read_csv(REPORT_DIR / "tablas" / "09_mix_apuestas.csv")
    D["met"] = pd.read_csv(REPORT_DIR / "tablas" / "12_metodos_recarga.csv")
    D["retp"] = pd.read_csv(REPORT_DIR / "tablas" / "14_retiros_procesamiento.csv")
    D["res"] = q("""SELECT sum(monto_apostado) FILTER (WHERE estado_ticket='liquidada') ap,
                    sum(monto_ganado) FILTER (WHERE estado_ticket='liquidada') pg FROM v_apuesta""").iloc[0]
    D["retencion"] = q("""SELECT cohorte_registro, count(*) FILTER (WHERE rec_n>0) conv,
                          count(*) FILTER (WHERE rec_n>0 AND activo_v1) act_v1
                          FROM mart.jugador_resumen WHERE historia_completa GROUP BY 1 ORDER BY 1""")
    D["rsa"] = q("""SELECT count(*) FILTER (WHERE rec_n>0 AND apu_n=0) sin, count(*) FILTER (WHERE rec_n>0) con
                    FROM mart.jugador_resumen WHERE en_registros""").iloc[0]
    D["rsa_monto"] = q("SELECT sum(rec_monto) FILTER (WHERE apu_n=0) a, sum(rec_monto) b FROM mart.jugador_resumen").iloc[0]
    D["verif"] = q("""SELECT verificacion_celular_cod c, count(*) n, avg((depositante_plataforma=1)::INT) p
                      FROM v_registro GROUP BY 1 ORDER BY 1""")
    D["cv"] = q("""SELECT s.ciclo_vida, count(*) total,
                   sum((s.estado_contacto='contactable_pendiente_consentimiento')::INT) contactables,
                   sum((NOT j.en_registros)::INT) sin_contacto,
                   sum(s.senal_revision_juego_responsable::INT) jr,
                   median(j.dias_desde_ultima_actividad) rec_med, median(j.rec_n) recargas_med, median(j.apu_n) apuestas_med
                   FROM mart.segmento_jugador s JOIN mart.jugador_resumen j USING (player_id) GROUP BY 1 ORDER BY 1""")
    D["hip"] = pd.read_csv(REPORT_DIR / "hipersegmentos_tamano.csv").set_index("etiqueta")
    D["pref"] = q("""SELECT pref_modalidad, count(*) n FROM mart.segmento_jugador WHERE pref_modalidad<>'insuficiente' GROUP BY 1""").set_index("pref_modalidad")
    D["params"] = q("SELECT parametro, valor FROM mart.parametros_segmentacion").set_index("parametro").valor
    D["params_base"] = q("SELECT parametro, valor FROM mart.parametros_segmentacion").set_index("parametro").valor
    D["cam"] = pd.read_csv(REPORT_DIR / "campanas_tamano.csv").set_index("campana")
    D["emb_aud"] = q("""SELECT campana, resultado, count(*) n FROM mart.audiencia_sms_detalle GROUP BY ALL""")
    D["hist"] = q("""SELECT count(*) FILTER (WHERE h_atrasado_vs_ritmo_propio) atrasado,
                     count(*) FILTER (WHERE ciclo_vida='4_enfriandose') enfriando,
                     count(*) FILTER (WHERE ciclo_vida='5_inactivo_31_60') inactivo
                     FROM mart.segmento_jugador s JOIN mart.jugador_resumen j USING (player_id)
                     WHERE NOT j.en_registros AND NOT s.senal_revision_juego_responsable""").iloc[0]
    D["telef"] = q("SELECT telefono_estado, count(*) n FROM v_registro GROUP BY 1").set_index("telefono_estado").n
    D["tel_comp"] = v("SELECT count(*) FROM v_registro WHERE jugadores_mismo_telefono>1")
    D["status"] = q("SELECT estado_cuenta_cod, count(*) n FROM v_registro GROUP BY 1 ORDER BY 2 DESC")
    D["mix_tot"] = q("SELECT live_cod, count(*) n FROM v_apuesta GROUP BY 1").set_index("live_cod").n
    D["bono"] = q("SELECT avg(con_fondos_bono) p, sum(monto_apostado) FILTER (WHERE con_fondos_bono=1)/sum(monto_apostado) m FROM v_apuesta").iloc[0]
    con.close()
    D["copies"] = pd.read_csv(ROOT / "campanas" / "sms_copies.csv")
    return D


# ───────────────────────── página ─────────────────────────
def cargar_app(D):
    """Datos adicionales para los módulos interactivos (todos agregados, sin datos personales)."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET VARIABLE fin_analisis = (SELECT max(fecha_corte) FROM mart.jugador_resumen)")
    for vista, tabla, col in [("v_recarga", "core.recarga", "fecha_hora"), ("v_apuesta", "core.apuesta", "fecha_hora")]:
        con.execute(f"CREATE OR REPLACE TEMP VIEW {vista} AS SELECT * FROM {tabla} WHERE {col} <= getvariable('fin_analisis')")
    D["cubo"] = con.execute("""
        SELECT s.ciclo_vida AS cv, s.nivel_valor AS nv, s.pref_modalidad AS pm,
               s.estado_contacto AS ec, s.senal_revision_juego_responsable::INT AS jr,
               j.en_registros::INT AS reg, coalesce(p.modelo || '_' || p.banda, 'sin_prediccion') AS pr,
               coalesce(o.op_modelo, 'sin_oportunidad') AS op, count(*) AS n
        FROM mart.segmento_jugador s JOIN mart.jugador_resumen j USING (player_id)
        LEFT JOIN (SELECT * FROM mart.prediccion_jugador WHERE modelo IN ('abandono', 'activacion')  -- en ambos: queda activación
                   QUALIFY row_number() OVER (PARTITION BY player_id ORDER BY (modelo = 'activacion') DESC) = 1) p USING (player_id)
        LEFT JOIN (SELECT player_id, modelo AS op_modelo FROM mart.prediccion_jugador   -- mejor oportunidad con probabilidad alta
                   WHERE banda = 'alta' AND modelo IN ('cruzada_deportes', 'habito', 'modalidad')
                   QUALIFY row_number() OVER (PARTITION BY player_id ORDER BY CASE modelo WHEN 'cruzada_deportes' THEN 1 WHEN 'habito' THEN 2 ELSE 3 END) = 1) o
          USING (player_id)
        GROUP BY ALL""").df()
    # Predicción: métricas de validación y pronóstico por segmento al corte.
    D["pred"] = json.loads((REPORT_DIR / "prediccion.json").read_text(encoding="utf-8"))
    D["afinidad"] = json.loads((REPORT_DIR / "afinidad_casino.json").read_text(encoding="utf-8"))
    D["pred_seg"] = con.execute("""
        SELECT p.modelo, s.ciclo_vida, j.en_registros reg, p.banda, count(*) n, sum(p.probabilidad) esperado,
               sum(p.probabilidad * (1 - p.probabilidad)) var,
               sum((s.estado_contacto = 'contactable_pendiente_consentimiento' AND NOT s.senal_revision_juego_responsable)::INT) contactables
        FROM mart.prediccion_jugador p JOIN mart.segmento_jugador s USING (player_id) JOIN mart.jugador_resumen j USING (player_id)
        GROUP BY ALL""").df()
    D["ctrl"] = con.execute("SELECT control, esperado, obtenido, estado, nota FROM meta.controles").df()
    D["perfil"] = con.execute("""
        SELECT en_registros AS reg,
               CASE WHEN rec_n>0 AND apu_n>0 THEN 'Recarga y apuesta' WHEN rec_n>0 THEN 'Solo recarga'
                    WHEN apu_n>0 THEN 'Solo apuesta' ELSE 'Sin recarga ni apuesta' END AS act,
               count(*) j, sum((ret_n>0)::INT) con_retiro, sum(rec_n) rec, sum(rec_monto) recm, sum(apu_n) apu,
               sum(apu_monto) apum, sum(ret_monto_neto) retm, median(rec_n) med_rec, median(apu_n) med_apu,
               median(greatest(rec_dias_activos, apu_dias_activos)) med_dias
        FROM mart.jugador_resumen GROUP BY ALL ORDER BY reg DESC, j DESC""").df()
    D["int_apu"] = con.execute("""
        SELECT CASE WHEN apu_dias_activos<=2 THEN '1-2 días' WHEN apu_dias_activos<=7 THEN '3-7 días'
                    WHEN apu_dias_activos<=30 THEN '8-30 días' WHEN apu_dias_activos<=60 THEN '31-60 días' ELSE '61-92 días' END b,
               count(*) j, sum(apu_n) n, 100*sum(apu_monto)/(SELECT sum(apu_monto) FROM mart.jugador_resumen) pm,
               median(apu_monto) med
        FROM mart.jugador_resumen WHERE apu_n>0 GROUP BY 1 ORDER BY min(apu_dias_activos)""").df()
    D["int_rec"] = con.execute("""
        SELECT CASE WHEN rec_n=1 THEN '1 recarga' WHEN rec_n<=3 THEN '2-3' WHEN rec_n<=10 THEN '4-10'
                    WHEN rec_n<=30 THEN '11-30' WHEN rec_n<=100 THEN '31-100' ELSE 'Más de 100' END b,
               count(*) j, sum(rec_n) n, 100*sum(rec_monto)/(SELECT sum(rec_monto) FROM mart.jugador_resumen) pm,
               median(rec_monto) med
        FROM mart.jugador_resumen WHERE rec_n>0 GROUP BY 1 ORDER BY min(rec_n)""").df()
    D["dicc"] = pd.read_csv(REPORT_DIR / "diccionario_datos.csv").fillna("")
    # Montos típicos por objetivo (medianas observadas en toda la base) para estimar el resultado de cada campaña.
    D["ticket"] = con.execute("""
        WITH f AS (SELECT r.player_id, r.monto, row_number() OVER (PARTITION BY r.player_id ORDER BY r.fecha_hora) k
                   FROM v_recarga r JOIN core.registro g USING (player_id) WHERE g.fecha_registro >= '2026-07-01'),
             a AS (SELECT x.player_id, x.monto_apostado m, row_number() OVER (PARTITION BY x.player_id ORDER BY x.fecha_hora) k
                   FROM v_apuesta x JOIN core.registro g USING (player_id) WHERE g.fecha_registro >= '2026-07-01'),
             u AS (SELECT player_id, max(fecha_hora) u FROM (SELECT player_id, fecha_hora FROM v_recarga UNION ALL
                   SELECT player_id, fecha_hora FROM v_apuesta) WHERE fecha_hora <= getvariable('fin_analisis') - INTERVAL 30 DAY GROUP BY 1),
             g AS (SELECT player_id FROM u WHERE date_diff('day', u, getvariable('fin_analisis') - INTERVAL 30 DAY) BETWEEN 8 AND 60),
             r14 AS (SELECT player_id, sum(monto) m FROM v_recarga WHERE fecha_hora > getvariable('fin_analisis') - INTERVAL 30 DAY
                     AND fecha_hora <= getvariable('fin_analisis') - INTERVAL 16 DAY GROUP BY 1)
        SELECT (SELECT median(monto) FROM f WHERE k = 1) primera, (SELECT median(monto) FROM f WHERE k = 2) segunda,
               (SELECT median(m) FROM a WHERE k = 1) apuesta1, (SELECT median(m) FROM r14 JOIN g USING (player_id)) retorno""").df().iloc[0]
    D["n_archivos"] = con.execute("SELECT count(*) FROM meta.manifiesto").fetchall()[0][0]
    D["n_cargados"] = con.execute("SELECT count(*) FROM meta.manifiesto WHERE estado='cargado'").fetchall()[0][0]
    # Seguimiento posterior al corte (datos parciales que llegan después)
    # Inicio de los datos de casino: la hipótesis de casino solo se mide en días que tienen casino.
    con.execute("SET VARIABLE cas_desde = (SELECT min(fecha_hora)::DATE::TIMESTAMP FROM core.casino)")
    con.execute(f"SET VARIABLE inicio_obs = TIMESTAMP '{INICIO_OBSERVACION}'")
    # Hipótesis de casino: de quienes recargaron en los días con casino sin apostar en deportes, cuántos jugaron casino.
    D["hip_cas"] = con.execute("""
        WITH r AS (SELECT DISTINCT player_id FROM core.recarga WHERE fecha_hora >= getvariable('cas_desde') AND fecha_hora <= getvariable('fin_analisis')),
             a AS (SELECT DISTINCT player_id FROM core.apuesta WHERE fecha_hora >= getvariable('cas_desde') AND fecha_hora <= getvariable('fin_analisis')),
             k AS (SELECT DISTINCT player_id FROM core.casino WHERE fecha_hora <= getvariable('fin_analisis'))
        SELECT count(*) recargan, count(*) FILTER (WHERE a.player_id IS NULL) sin_dep,
               count(*) FILTER (WHERE a.player_id IS NULL AND k.player_id IS NOT NULL) sin_dep_cas,
               count(*) FILTER (WHERE a.player_id IS NOT NULL AND k.player_id IS NOT NULL) dep_cas
        FROM r LEFT JOIN a USING (player_id) LEFT JOIN k USING (player_id)""").df().iloc[0]
    # Tasas naturales (sin SMS): corte simulado 30 días antes del corte; se mide qué hizo cada grupo después.
    con.execute("SET VARIABLE t_sim = getvariable('fin_analisis') - INTERVAL 30 DAY")
    D["t_sim"] = con.execute("SELECT getvariable('t_sim')").fetchall()[0][0]
    D["tasas"] = con.execute("""
        WITH t AS (SELECT getvariable('t_sim') t),
             reg AS (SELECT player_id, fecha_registro f FROM core.registro WHERE fecha_registro >= getvariable('inicio_obs')),
             rec AS (SELECT player_id, fecha_hora f FROM core.recarga WHERE fecha_hora <= getvariable('fin_analisis')),
             apu AS (SELECT player_id, fecha_hora f FROM core.apuesta WHERE fecha_hora <= getvariable('fin_analisis')),
             act AS (SELECT * FROM rec UNION ALL SELECT * FROM apu),
             antes AS (SELECT player_id, count(*) FILTER (WHERE src='r') nr, count(*) FILTER (WHERE src='a') na,
                              max(f) FILTER (WHERE src='r') ult_r, min(f) FILTER (WHERE src='r') pri_r, max(f) ult
                       FROM (SELECT player_id, f, 'r' src FROM rec UNION ALL SELECT player_id, f, 'a' FROM apu), t WHERE f <= t.t GROUP BY 1),
             desp AS (SELECT player_id,
                             min(f) FILTER (WHERE src='r') r1, min(f) FILTER (WHERE src='a') a1, min(f) x1
                      FROM (SELECT player_id, f, 'r' src FROM rec UNION ALL SELECT player_id, f, 'a' FROM apu), t WHERE f > t.t GROUP BY 1),
             g AS (
               SELECT 'ACT01' c, reg.player_id, (d.r1 <= t.t + INTERVAL 7 DAY) ok FROM t, reg LEFT JOIN antes b USING (player_id) LEFT JOIN desp d USING (player_id)
                 WHERE reg.f > t.t - INTERVAL 7 DAY AND reg.f <= t.t AND coalesce(b.nr, 0) = 0 AND coalesce(b.na, 0) = 0
               UNION ALL
               SELECT 'ACT05', reg.player_id, (d.r1 <= t.t + INTERVAL 14 DAY) FROM t, reg LEFT JOIN antes b USING (player_id) LEFT JOIN desp d USING (player_id)
                 WHERE reg.f > t.t - INTERVAL 30 DAY AND reg.f <= t.t - INTERVAL 7 DAY AND coalesce(b.nr, 0) = 0 AND coalesce(b.na, 0) = 0
               UNION ALL
               SELECT 'ONB02', b.player_id, (d.r1 <= t.t + INTERVAL 14 DAY) FROM t, antes b LEFT JOIN desp d USING (player_id)
                 WHERE b.nr = 1 AND b.pri_r <= t.t - INTERVAL 7 DAY AND b.ult <= t.t - INTERVAL 7 DAY
                   AND b.player_id IN (SELECT player_id FROM reg)
               UNION ALL
               SELECT 'XS03', b.player_id, (d.a1 <= t.t + INTERVAL 30 DAY) FROM t, antes b LEFT JOIN desp d USING (player_id)
                 WHERE b.nr > 0 AND b.na = 0 AND b.ult_r >= t.t - INTERVAL 60 DAY AND b.player_id IN (SELECT player_id FROM reg)
               UNION ALL
               SELECT 'RET04', b.player_id, (d.x1 <= t.t + INTERVAL 14 DAY) FROM t, antes b LEFT JOIN desp d USING (player_id)
                 WHERE b.ult BETWEEN t.t - INTERVAL 30 DAY AND t.t - INTERVAL 15 DAY
               UNION ALL
               SELECT 'REC06', b.player_id, (d.x1 <= t.t + INTERVAL 14 DAY) FROM t, antes b LEFT JOIN desp d USING (player_id)
                 WHERE b.ult BETWEEN t.t - INTERVAL 60 DAY AND t.t - INTERVAL 31 DAY)
        SELECT c, count(*) n, avg(coalesce(ok, false)::INT) tasa FROM g GROUP BY 1""").df().set_index("c")
    D["cas"] = con.execute("""SELECT count(*) rondas, count(DISTINCT player_id) jug, sum(monto_apostado) ap, sum(monto_ganado) pg,
        median(monto_apostado) med, count(DISTINCT juego) juegos, min(fecha_hora)::DATE d0, max(fecha_hora)::DATE d1 FROM core.casino""").df().iloc[0]
    D["cas_prov"] = con.execute("""SELECT proveedor, count(*) rondas, count(DISTINCT player_id) jug,
        100*sum(monto_apostado)/(SELECT sum(monto_apostado) FROM core.casino) pm FROM core.casino GROUP BY 1 ORDER BY pm DESC""").df()
    D["cas_hora"] = con.execute("SELECT hour(fecha_hora) h, count(*) n FROM core.casino GROUP BY 1 ORDER BY 1").df()
    D["cas_base"] = con.execute("""SELECT CASE WHEN j.en_registros THEN 'Registrados desde julio'
        ELSE 'Base anterior a julio' END g, count(*) n FROM (SELECT DISTINCT player_id FROM core.casino) c
        LEFT JOIN mart.jugador_resumen j USING (player_id) GROUP BY 1 ORDER BY 2 DESC""").df()
    D["cas_top"] = con.execute("""WITH g AS (SELECT player_id, sum(monto_apostado) m FROM core.casino GROUP BY 1),
        r AS (SELECT m, ntile(100) OVER (ORDER BY m DESC) p FROM g)
        SELECT 100*sum(m) FILTER (WHERE p=1)/sum(m) t1, 100*sum(m) FILTER (WHERE p<=10)/sum(m) t10 FROM r""").df().iloc[0]
    D["dia_fuente"] = con.execute("""
        SELECT fecha_registro::DATE d, 'registros' fuente, count(*) n, NULL::DOUBLE m, count(*) j FROM core.registro
            WHERE fecha_registro >= getvariable('inicio_obs') AND fecha_registro <= getvariable('fin_analisis') GROUP BY 1
        UNION ALL SELECT fecha_hora::DATE, 'recargas', count(*), sum(monto), count(DISTINCT player_id) FROM core.recarga
            WHERE fecha_hora <= getvariable('fin_analisis') GROUP BY 1
        UNION ALL SELECT fecha_hora::DATE, 'apuestas', count(*), sum(monto_apostado), count(DISTINCT player_id) FROM core.apuesta
            WHERE fecha_hora <= getvariable('fin_analisis') GROUP BY 1
        UNION ALL SELECT fecha_hora::DATE, 'casino', count(*), sum(monto_apostado), count(DISTINCT player_id) FROM core.casino GROUP BY 1
        UNION ALL SELECT fecha_ultima_actualizacion::DATE, 'retiros', count(*), sum(monto_neto), count(DISTINCT player_id) FROM core.retiro
            WHERE fecha_ultima_actualizacion <= getvariable('fin_analisis') GROUP BY 1
        ORDER BY 1, 2""").df()
    D["cobertura"] = con.execute("SELECT dia, fuente, estado FROM meta.cobertura_dia ORDER BY 1, 2").df()
    con.close()
    return D


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


CSS = r"""
:root{
  /* Layout: consola de producto Vincero; barra lateral fija con módulos, barra superior con estado del espacio de trabajo y área de trabajo por paneles */
  --side:#0A0A0B; --side-fg:#F2F2F3; --side-mute:#8C8C93; --side-act:#1C1C1F;
  --bg:#F4F4F3; --panel:#FFFFFF; --panel2:#FAFAF9; --fg:#0A0A0B; --fg2:#5B5B62; --line:#E3E3E1; --grid:#ECECEA;
  --accent:#2F5BFF; --accent-soft:#E8EDFF; --accent-fg:#FFFFFF;
  --s1:#0A0A0B; --s2:#2F5BFF; --dot:#2F5BFF;
  --q0:#EEF2FF; --q1:#D3DDFF; --q2:#A9BCFF; --q3:#7B97FF; --q4:#4F70F5; --q5:#2D4FD6; --q6:#1A329E;
  --ok:#0B7A43; --ok-bg:#E5F4EC; --warn:#9A5B00; --warn-bg:#FCF1DF; --crit:#B42318; --crit-bg:#FCE8E6;
  --f-ui:'Geist', 'Inter', 'Segoe UI', system-ui, sans-serif;
  --f-mono:'Geist Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --side:#000000; --side-act:#18181B; --bg:#0C0C0E; --panel:#141417; --panel2:#18181C; --fg:#EDEDEF; --fg2:#9A9AA2;
  --line:#26262B; --grid:#212126; --accent:#7090FF; --accent-soft:#1B2340; --accent-fg:#0A0A0B;
  --s1:#E4E4E7; --s2:#7090FF; --dot:#7090FF;
  --q0:#141A30; --q1:#1B2650; --q2:#24367A; --q3:#2F4BAA; --q4:#4766D6; --q5:#7090FF; --q6:#B3C3FF;
  --ok:#4CC38A; --ok-bg:#0F2A1D; --warn:#F0A43A; --warn-bg:#2C2010; --crit:#F07067; --crit-bg:#2E1514; color-scheme:dark }}
:root[data-theme="dark"]{
  --side:#000000; --side-act:#18181B; --bg:#0C0C0E; --panel:#141417; --panel2:#18181C; --fg:#EDEDEF; --fg2:#9A9AA2;
  --line:#26262B; --grid:#212126; --accent:#7090FF; --accent-soft:#1B2340; --accent-fg:#0A0A0B;
  --s1:#E4E4E7; --s2:#7090FF; --dot:#7090FF;
  --q0:#141A30; --q1:#1B2650; --q2:#24367A; --q3:#2F4BAA; --q4:#4766D6; --q5:#7090FF; --q6:#B3C3FF;
  --ok:#4CC38A; --ok-bg:#0F2A1D; --warn:#F0A43A; --warn-bg:#2C2010; --crit:#F07067; --crit-bg:#2E1514; color-scheme:dark }
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{height:100%}
body{background:var(--bg);color:var(--fg);font-family:var(--f-ui);font-size:14px;line-height:1.55;margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:20;background:var(--side)}
h1,h2,h3,h4{margin:0;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
h1{font-size:1.45rem} h2{font-size:1.05rem} h3{font-size:.95rem} h4{font-size:.88rem}
p{margin:0;max-width:78ch}
code{font-family:var(--f-mono);font-size:.82em;background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.num,.mono{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

/* Shell */
.app{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:100%}
.side{background:var(--side);color:var(--side-fg);position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:18px;
  padding:20px 14px max(16px,env(safe-area-inset-bottom,0px)) max(14px,env(safe-area-inset-left,0px))}
.brand{display:flex;align-items:center;padding:4px 8px 6px}
.brand img{height:16px;width:auto}
.ws{border:1px solid #232327;border-radius:8px;padding:10px 12px;display:grid;gap:2px}
.ws small{color:var(--side-mute);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase}
.ws b{font-weight:600;font-size:.9rem}
.ws span{font-family:var(--f-mono);font-size:.72rem;color:var(--side-mute)}
.nav{display:grid;gap:2px}
.nav .grp{color:var(--side-mute);font-size:.66rem;letter-spacing:.12em;text-transform:uppercase;padding:12px 10px 4px}
.nav a{display:flex;align-items:center;gap:10px;color:#C9C9CE;text-decoration:none;padding:7px 10px;border-radius:6px;font-size:.86rem}
.nav a:hover{background:var(--side-act);color:#fff}
.nav a.on{background:var(--side-act);color:#fff;box-shadow:inset 2px 0 0 var(--accent)}
.nav a i{width:16px;height:16px;flex:none;opacity:.85}
.nav a .badge{margin-left:auto;font-family:var(--f-mono);font-size:.68rem;color:var(--side-mute)}
.side-foot{margin-top:auto;display:grid;gap:6px;font-size:.74rem;color:var(--side-mute)}
.side-foot .row{display:flex;align-items:center;gap:8px}
.led{width:7px;height:7px;border-radius:50%;background:#4CC38A;box-shadow:0 0 0 3px rgba(76,195,138,.18)}
.led.w{background:#F0A43A;box-shadow:0 0 0 3px rgba(240,164,58,.18)}

.main{min-width:0;display:flex;flex-direction:column}
.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:10;background:var(--panel);border-bottom:1px solid var(--line);
  display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding-block:12px;
  padding-left:max(24px,env(safe-area-inset-left,0px));padding-right:max(24px,env(safe-area-inset-right,0px))}
.crumb{font-size:.84rem;color:var(--fg2);display:flex;gap:8px;align-items:center}
.crumb b{color:var(--fg);font-weight:600}
.top .status{margin-left:auto;display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:.74rem;font-weight:500;padding:4px 10px;border-radius:99px;border:1px solid var(--line);background:var(--panel2);white-space:nowrap;color:var(--fg2)}
.chip .led{width:6px;height:6px}
.chip.ok{color:var(--ok);background:var(--ok-bg);border-color:transparent}
.chip.warn{color:var(--warn);background:var(--warn-bg);border-color:transparent}
.chip.crit{color:var(--crit);background:var(--crit-bg);border-color:transparent}
.chip.acc{color:var(--accent);background:var(--accent-soft);border-color:transparent}
.chip.ok::before,.chip.warn::before,.chip.crit::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}

.content{padding-block:24px 48px;padding-left:max(24px,env(safe-area-inset-left,0px));padding-right:max(24px,env(safe-area-inset-right,0px));display:grid;gap:18px;max-width:1320px;width:100%}
.view{display:grid;gap:18px}
.vhead{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px}
.vhead p{color:var(--fg2);font-size:.9rem;margin-top:4px}

/* Paneles */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;min-width:0;display:flex;flex-direction:column}
.ph{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;padding:12px 16px;border-bottom:1px solid var(--line)}
.ph h2{font-size:.92rem}
.ph .sub{font-size:.76rem;color:var(--fg2)}
.pb{padding:14px 16px;display:grid;gap:12px;min-width:0}
.pb.flush{padding:0}
.g{display:grid;gap:18px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.g-73{grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)}
@media (max-width:1100px){.g4{grid-template-columns:repeat(2,minmax(0,1fr))}.g3{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:820px){.g2,.g3,.g-73{grid-template-columns:minmax(0,1fr)}}
@media (max-width:520px){.g4{grid-template-columns:minmax(0,1fr)}}

.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:grid;gap:6px;align-content:start}
.tile .lab{font-size:.74rem;color:var(--fg2);text-transform:uppercase;letter-spacing:.06em}
.tile .val{font-family:var(--f-mono);font-size:1.7rem;font-weight:600;letter-spacing:-.02em;line-height:1.1}
.tile .val small{font-size:.9rem;color:var(--fg2);font-weight:500}
.tile .ft{font-size:.8rem;color:var(--fg2)}
.tile.acc{border-color:var(--accent);box-shadow:inset 0 3px 0 var(--accent)}

.list{display:grid}
.li{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:start;padding:11px 16px;border-top:1px solid var(--line)}
.li:first-child{border-top:0}
.li .ic{width:28px;height:28px;border-radius:7px;display:grid;place-items:center;font-family:var(--f-mono);font-size:.7rem;font-weight:600}
.ic.ok{background:var(--ok-bg);color:var(--ok)} .ic.warn{background:var(--warn-bg);color:var(--warn)} .ic.crit{background:var(--crit-bg);color:var(--crit)} .ic.acc{background:var(--accent-soft);color:var(--accent)}
.li b{font-weight:600;font-size:.88rem;display:block}
.li span{font-size:.82rem;color:var(--fg2)}

/* Tablas */
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.84rem;min-width:560px}
thead th{position:sticky;top:0;background:var(--panel2);color:var(--fg2);font-weight:500;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;text-align:left;padding:9px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody td{padding:9px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--panel2)}
td.num,th.num{text-align:right;font-family:var(--f-mono);font-variant-numeric:tabular-nums;white-space:nowrap}
table.wide{min-width:960px}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:.72rem;font-weight:500;padding:2px 8px;border-radius:99px;white-space:nowrap}
.pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.ok{color:var(--ok);background:var(--ok-bg)} .pill.warn{color:var(--warn);background:var(--warn-bg)}
.pill.crit{color:var(--crit);background:var(--crit-bg)} .pill.neu{color:var(--fg2);background:var(--panel2);border:1px solid var(--line)}

/* Controles de formulario */
.search{display:flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:8px;padding:6px 10px;background:var(--panel);min-width:0}
.search input{border:0;outline:0;background:transparent;font:inherit;color:var(--fg);width:220px;max-width:100%}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;flex-wrap:wrap}
.seg button{border:0;background:var(--panel);padding:6px 12px;font-size:.8rem;cursor:pointer;color:var(--fg2)}
.seg a.btn{text-decoration:none;border:0;border-radius:0;color:var(--fg2)}
.seg a.btn + a.btn{border-left:1px solid var(--line)}
.seg button + button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:var(--fg);color:var(--panel)}
.checks{display:grid;gap:6px}
.checks label{display:flex;align-items:center;gap:8px;font-size:.84rem;cursor:pointer}
.checks label .ct{margin-left:auto;font-family:var(--f-mono);font-size:.76rem;color:var(--fg2)}
.checks input{accent-color:var(--accent);width:15px;height:15px}
.fgroup{display:grid;gap:8px;align-content:start}
.fgroup h4{font-size:.74rem;text-transform:uppercase;letter-spacing:.08em;color:var(--fg2);font-weight:500}
.btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:6px 12px;font-size:.8rem;cursor:pointer}
.btn:hover{border-color:var(--fg2)}
.big{font-family:var(--f-mono);font-size:2.4rem;font-weight:600;letter-spacing:-.02em;line-height:1}
.bar{height:8px;border-radius:99px;background:var(--grid);overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);border-radius:99px;transition:width .25s}
@media (prefers-reduced-motion:reduce){.bar i{transition:none}}

/* Insights */
.ins{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:0}
@media (max-width:980px){.ins{grid-template-columns:minmax(0,1fr)}}
.ins .txt{padding:14px 16px;display:grid;gap:10px;align-content:start;border-right:1px solid var(--line)}
@media (max-width:980px){.ins .txt{border-right:0;border-bottom:1px solid var(--line)}}
.ins .fig{padding:12px 16px;min-width:0}
.ins.one{grid-template-columns:minmax(0,1fr)}
.ins.one .txt{border-right:0}
.kv{display:grid;grid-template-columns:110px minmax(0,1fr);gap:6px 12px;font-size:.84rem;margin:0}
.kv dt{color:var(--fg2);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;padding-top:2px}
.kv dd{margin:0}
.kv dd.act{font-weight:600}
.metric{display:flex;align-items:baseline;gap:8px}
.metric b{font-family:var(--f-mono);font-size:1.6rem;font-weight:600}
.metric span{color:var(--fg2);font-size:.82rem}

/* Gráficos */
svg.chart{width:100%;height:auto;display:block}
svg .grid{stroke:var(--grid);stroke-width:1}
svg .ax{fill:var(--fg2);font-family:var(--f-ui);font-size:11.5px}
svg .ax.mute{font-size:10.5px}
svg .lbl{fill:var(--fg);font-family:var(--f-mono);font-size:11px}
svg .line{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round}
svg .dot{fill:var(--dot);stroke:var(--panel);stroke-width:2}
svg .hit{fill:transparent}
svg rect:hover,svg path:hover{opacity:.8}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.78rem;color:var(--fg2);margin-bottom:6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.dotsw{border-radius:50%;background:var(--dot)}
.sm-title{font-size:.8rem;font-weight:600;margin-top:4px}
.scale{display:flex;align-items:center;gap:3px;font-size:.74rem;color:var(--fg2);margin-top:4px;flex-wrap:wrap}
.scale i{width:22px;height:10px;border-radius:2px;display:inline-block}
.scale span{margin-inline:6px}

/* Pipeline */
.flow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:0}
@media (max-width:980px){.flow{grid-template-columns:repeat(2,minmax(0,1fr))}}
.flow .st{padding:14px 16px;border-right:1px solid var(--line);display:grid;gap:4px;position:relative}
.flow .st:last-child{border-right:0}
.flow .st b{font-size:.86rem}
.flow .st code{background:none;border:0;padding:0;color:var(--accent);font-size:.74rem}
.flow .st span{font-size:.78rem;color:var(--fg2)}
.flow .st .n{font-family:var(--f-mono);font-size:1.1rem;font-weight:600;color:var(--fg)}

/* Campañas */
.cm{display:grid;grid-template-columns:300px minmax(0,1fr);gap:18px;align-items:start}
@media (max-width:980px){.cm{grid-template-columns:minmax(0,1fr)}}
.clist{display:grid}
.citem{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 10px;text-align:left;border:0;border-top:1px solid var(--line);background:var(--panel);padding:12px 14px;cursor:pointer}
.citem:first-child{border-top:0}
.citem:hover{background:var(--panel2)}
.citem[aria-selected="true"]{background:var(--accent-soft);box-shadow:inset 3px 0 0 var(--accent)}
.citem .code{grid-row:span 2;font-family:var(--f-mono);font-size:.7rem;font-weight:600;background:var(--fg);color:var(--panel);border-radius:5px;padding:3px 6px;align-self:start}
.citem b{font-size:.86rem;font-weight:600}
.citem span{font-size:.76rem;color:var(--fg2);font-family:var(--f-mono)}
.cdet{display:grid;gap:18px}
.phone{width:min(300px,100%);border:1px solid var(--line);border-radius:28px;padding:14px 12px 18px;background:var(--panel2);display:grid;gap:10px;justify-self:center}
.phone .notch{width:70px;height:6px;border-radius:99px;background:var(--line);justify-self:center}
.phone .from{font-size:.72rem;color:var(--fg2);text-align:center}
.bubble{background:var(--panel);border:1px solid var(--line);border-radius:16px 16px 16px 4px;padding:10px 12px;font-size:.84rem;line-height:1.45}
.bubble .lk{color:var(--accent);font-weight:500}
.smeta{font-family:var(--f-mono);font-size:.7rem;color:var(--fg2);text-align:center}
.vars{display:flex;gap:6px;flex-wrap:wrap;justify-content:center}

/* Roadmap */
.road{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}
@media (max-width:1100px){.road{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:560px){.road{grid-template-columns:minmax(0,1fr)}}
.col{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;gap:8px;align-content:start}
.col h3{display:flex;justify-content:space-between;gap:8px;font-size:.84rem}
.col h3 span{font-family:var(--f-mono);font-size:.72rem;color:var(--fg2);font-weight:500}
.task{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.8rem;display:grid;gap:6px}
.task .own{font-size:.7rem;color:var(--fg2);font-family:var(--f-mono)}

/* Ayuda contextual: el detalle se abre al pasar el cursor o al tocar el ícono */
.info{position:relative;display:inline-grid;place-items:center;width:15px;height:15px;margin-left:5px;border-radius:50%;border:1px solid var(--line);
  font:600 .62rem/1 var(--f-ui);color:var(--fg2);cursor:help;vertical-align:1px;text-transform:none;letter-spacing:0}
.info::after{content:attr(data-tip);position:absolute;z-index:30;left:50%;bottom:calc(100% + 8px);transform:translateX(-50%);width:max-content;max-width:280px;
  padding:8px 10px;border-radius:8px;background:var(--fg);color:var(--panel);font:400 .76rem/1.45 var(--f-ui);text-align:left;white-space:normal;
  opacity:0;pointer-events:none;transition:opacity .12s}
.info:hover::after,.info:focus::after{opacity:1}
@media (max-width:860px){.info::after{left:auto;right:-8px;transform:none;max-width:240px}}
.todo{display:grid;gap:2px;border-left:3px solid var(--accent);padding:4px 0 4px 10px;font-size:.86rem}
.todo b{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}
details.how{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:10px 14px;font-size:.84rem}
details.how summary{cursor:pointer;font-weight:500;color:var(--fg2)}
details.how[open] summary{margin-bottom:6px}
.note{border:1px solid var(--line);border-left:3px solid var(--accent);background:var(--panel);border-radius:8px;padding:12px 14px;display:grid;gap:4px;font-size:.86rem}
.note b{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}
.muted{color:var(--fg2)} .small{font-size:.8rem}


/* Simulador y pasos de campaña */
.simctl{display:flex;flex-wrap:wrap;gap:18px 28px;align-items:flex-end}
.simctl .search input{width:170px}
.steps{display:grid;gap:12px}
.step{display:grid;grid-template-columns:34px minmax(0,1fr);gap:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.step .sn{width:28px;height:28px;border-radius:50%;background:var(--fg);color:var(--panel);display:grid;place-items:center;font-family:var(--f-mono);font-weight:600;font-size:.8rem}
.step .sb{display:grid;gap:8px;min-width:0}
.step h3{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.step h3 .sub{font-weight:400;font-size:.76rem;color:var(--fg2)}
.step.res{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.msg{display:grid;gap:10px;justify-items:start}
.msg .phone{justify-self:start}
.rgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
@media (max-width:980px){.rgrid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.rgrid div{border:1px solid var(--line);border-radius:8px;padding:10px 12px;display:grid;gap:2px;align-content:start}
.rgrid div.hl{background:var(--accent-soft);border-color:transparent}
.rgrid span{font-size:.72rem;color:var(--fg2);text-transform:uppercase;letter-spacing:.05em}
.rgrid b{font-family:var(--f-mono);font-size:1.3rem;font-weight:600}
.rgrid small{font-size:.74rem;color:var(--fg2);line-height:1.35}
.tl{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:0;counter-reset:t}
@media (max-width:980px){.tl{grid-template-columns:minmax(0,1fr)}}
.tl li{position:relative;padding:22px 12px 4px 0;display:grid;gap:4px;border-top:3px solid var(--line)}
.tl li::before{content:"";position:absolute;top:-8px;left:0;width:13px;height:13px;border-radius:50%;background:var(--accent);border:3px solid var(--panel)}
@media (max-width:980px){.tl li{border-top:0;border-left:3px solid var(--line);padding:4px 0 14px 18px}.tl li::before{top:4px;left:-8px}}
.tl .d{font-family:var(--f-mono);font-size:.74rem;color:var(--accent);font-weight:600}
.tl b{font-size:.86rem}
.tl span:last-child{font-size:.8rem;color:var(--fg2)}
.cmp{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
@media (max-width:620px){.cmp{grid-template-columns:minmax(0,1fr)}}
.cmp div{border:1px solid var(--line);border-radius:8px;padding:12px;display:grid;gap:3px}
.cmp div.hl{background:var(--accent-soft);border-color:transparent}
.cmp span{font-size:.72rem;color:var(--fg2);text-transform:uppercase;letter-spacing:.05em}
.cmp b{font-family:var(--f-mono);font-size:1.15rem}
.cmp em{font-style:normal;font-size:.82rem}
table.gantt td{white-space:nowrap}
table.gantt td:first-child{white-space:normal;font-weight:500;min-width:220px}
table.gantt td:nth-child(n+3){border-left:1px dashed var(--line);min-width:104px}
.b{display:inline-block;font-style:normal;font-size:.72rem;font-weight:500;padding:3px 8px;border-radius:5px}
.b.ok{background:var(--ok-bg);color:var(--ok)} .b.warn{background:var(--warn-bg);color:var(--warn)}
.b.crit{background:var(--crit-bg);color:var(--crit)} .b.acc{background:var(--accent-soft);color:var(--accent)}
.b.neu{background:var(--panel2);color:var(--fg2);border:1px solid var(--line)}
.panel.ask{border-color:var(--crit)}

/* Móvil: la barra lateral pasa a ser una barra horizontal superior */
@media (max-width:860px){
  .app{grid-template-columns:minmax(0,1fr)}
  .side{position:sticky;top:0;height:auto;z-index:15;flex-direction:row;align-items:center;gap:10px;overflow-x:auto;
    padding:10px max(16px,env(safe-area-inset-right,0px)) 10px max(16px,env(safe-area-inset-left,0px))}
  .ws,.side-foot,.nav .grp{display:none}
  .brand{flex:none;padding:0}
  .nav{display:flex;gap:2px}
  .nav a{white-space:nowrap;padding:6px 10px}
  .nav a i,.nav a .badge{display:none}
  .top{position:static;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
  .top .status{margin-left:0}
  .content{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
}
"""

ICON = {  # trazos simples, 16x16
    "home": '<path d="M2 7.5 8 2.5l6 5V14H10v-4H6v4H2z"/>',
    "db": '<ellipse cx="8" cy="3.5" rx="5.5" ry="2"/><path d="M2.5 3.5v9c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2v-9M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/>',
    "model": '<rect x="1.5" y="2" width="5" height="4" rx="1"/><rect x="9.5" y="2" width="5" height="4" rx="1"/><rect x="5.5" y="10" width="5" height="4" rx="1"/><path d="M4 6v2h8V6M8 8v2"/>',
    "book": '<path d="M2.5 2.5h4.5a1.5 1.5 0 0 1 1 1.5v10a1.5 1.5 0 0 0-1-1H2.5zM13.5 2.5H9a1.5 1.5 0 0 0-1 1.5v10a1.5 1.5 0 0 1 1-1h4.5z"/>',
    "spark": '<path d="M2 12 6 7l3 3 5-7"/><circle cx="14" cy="3" r=".5"/>',
    "users": '<circle cx="6" cy="5.5" r="2.5"/><path d="M1.5 14c.5-2.5 2.3-4 4.5-4s4 1.5 4.5 4"/><circle cx="11.5" cy="5" r="2"/><path d="M11 9.5c1.8 0 3.2 1.2 3.5 3.5"/>',
    "filter": '<path d="M2 3h12l-4.5 5.5V13L6.5 14V8.5z"/>',
    "send": '<path d="M14.5 1.5 7 9M14.5 1.5 10 14.5 7 9 1.5 6z"/>',
    "gauge": '<path d="M2 11a6 6 0 1 1 12 0"/><path d="M8 11l3-4"/>',
    "map": '<path d="M1.5 3.5 5.5 2l5 2 4-1.5v10l-4 1.5-5-2-4 1.5z"/><path d="M5.5 2v10M10.5 4v10"/>',
    "cog": '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>',
}


# Módulos que existen en el código pero no se muestran en la app del cliente.
# Modelo y Diccionario son documentación técnica (docs/ y reports/diccionario_datos.csv);
# Plan era un cronograma, no una función del software.
# Fuentes de datos (manifiesto y controles) es de uso interno: los controles siguen corriendo y se ven en reports/controles.csv.
MODULOS_OCULTOS = {"modelo", "diccionario", "plan", "datos"}
# None: el enlace "Ver" se quita en lugar de llevar a otro módulo.
REDIRIGIR = {"plan": "campanas", "modelo": None, "diccionario": None, "datos": None}


def ocultar_modulos(html_txt):
    """Quita del HTML las vistas ocultas y apunta sus enlaces a un módulo visible."""
    for k in MODULOS_OCULTOS:
        i = html_txt.find(f'<section class="view" id="v-{k}"')
        if i >= 0:
            j = min(x for x in (html_txt.find('<section class="view"', i + 10), html_txt.find("</main>", i)) if x > 0)
            html_txt = html_txt[:i] + html_txt[j:]
        if REDIRIGIR[k]:
            html_txt = html_txt.replace(f'href="#{k}"', f'href="#{REDIRIGIR[k]}"')
        else:
            html_txt = re.sub(rf'<a class="btn" href="#{k}">[^<]*</a>', '<span></span>', html_txt)
    return html_txt


def icon(k):
    return f'<i aria-hidden="true"><svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">{ICON[k]}</svg></i>'


VISTAS_ACTIVACION = r"""<section class="view" id="v-campanas" data-title="Campañas SMS">
  <div class="vhead"><div><h1>Campañas SMS</h1><p>Seis campañas listas para enviar: resultado esperado y detalle de cada una.</p></div></div>
  <section class="panel sim"><div class="ph"><h2>¿Qué resultado podemos esperar?</h2><span class="sub">Escenarios, no pronósticos: el grupo de control medirá el efecto real</span></div>
    <div class="pb">
      <div class="simctl">
        <div class="fgroup"><h4>Efecto del SMS sobre la tasa natural</h4>
          <div class="seg" id="esc">
            <button type="button" data-l="0" aria-pressed="false">Ninguno</button>
            <button type="button" data-l="0.1" aria-pressed="false">Conservador +10 %</button>
            <button type="button" data-l="0.25" aria-pressed="true">Base +25 %</button>
            <button type="button" data-l="0.5" aria-pressed="false">Optimista +50 %</button>
          </div></div>
        <div class="fgroup"><h4><label for="tarifa">Tarifa por SMS (COP)</label></h4>
          <label class="search"><span class="muted small">$</span><input id="tarifa" type="number" min="0" step="1" placeholder="Tarifa del proveedor" inputmode="numeric"></label></div>
      </div>
      <div class="g g4" id="sim-tiles">
        <div class="tile"><div class="lab">SMS a enviar</div><div class="val" id="s-env">—</div><div class="ft">Uno por jugador en la ola. Otros <span id="s-ctl" class="mono">—</span> quedan sin mensaje como grupo de control.</div></div>
        <div class="tile"><div class="lab">Lo que pasaría sin SMS</div><div class="val" id="s-sin">—</div><div class="ft">Recargas o apuestas que igual ocurrirían sin enviar nada, según lo que hicieron jugadores parecidos en semanas anteriores.</div></div>
        <div class="tile acc"><div class="lab">Lo que agregaría el SMS</div><div class="val" id="s-add">—</div><div class="ft" id="s-add-l">—</div></div>
        <div class="tile"><div class="lab">Costo por cada acción que agrega el SMS</div><div class="val" id="s-cpa">—</div><div class="ft" id="s-cost">Escribe arriba la tarifa por SMS del proveedor para calcularlo.</div></div>
      </div>
      <div class="tw"><table class="wide"><thead><tr><th>Campaña</th><th>Objetivo</th><th class="num">SMS</th><th class="num">Tasa natural</th><th class="num">Sin SMS</th><th class="num">Con SMS</th><th class="num">Adicionales</th><th class="num">Monto asociado</th><th class="num">Costo / adicional</th><th>¿Se podrá confirmar?</th></tr></thead><tbody id="sim-body"></tbody></table></div>
      <div class="note"><b>Lectura de Vincero</b><span>Con efectos realistas (+10 % a +25 %), una sola ola no alcanza para confirmar resultados. Leer la ola 1 como piloto, acumular 2 o 3 olas y conseguir la base histórica para ganar volumen.</span></div>
      <p class="small muted">Tasa natural: lo que hizo un grupo equivalente sin SMS en un corte simulado al {T_SIM}, 30 días antes del corte. Monto asociado: acciones adicionales × monto mediano de esa acción (recarga o apuesta). "Se podrá confirmar" compara el efecto del escenario con el efecto mínimo detectable del grupo de control.</p>
    </div></section>
  <div class="cm">
    <section class="panel"><div class="ph"><h2>Campañas</h2><span class="sub">por prioridad</span></div><div class="clist" role="tablist">{ITEMS}
      <button type="button" class="citem" disabled style="cursor:not-allowed;opacity:.7"><span class="code">HIST07</span><b>7. Retención base histórica</b><span>Bloqueada: sin teléfonos · {HIST} potenciales</span></button></div></section>
    <div>{DETS}</div>
  </div>
</section>

<section class="view" id="v-medicion" data-title="Medición">
  <div class="vhead"><div><h1>Medición</h1><p>Cada campaña se mide contra un grupo que no recibe SMS.</p></div></div>
  <section class="panel"><div class="ph"><h2>Línea de tiempo de una ola</h2></div><div class="pb">
    <ol class="tl">
      <li><span class="d">Día 0</span><b>Selección y sorteo</b><span>Audiencia al corte, cruce con lista de supresión y división envío / control (80 / 20).</span></li>
      <li><span class="d">Día 1</span><b>Envío</b><span>Solo al grupo envío, dentro del horario permitido. El proveedor reporta entregas.</span></li>
      <li><span class="d">Días 1-3</span><b>Entregas y clics</b><span>Tasa de entrega y clics por enlace individual con UTM. Señal temprana, no resultado.</span></li>
      <li><span class="d">Día 7</span><b>Lectura ACT01</b><span>Primera recarga en 7 días, envío frente a control.</span></li>
      <li><span class="d">Día 14</span><b>Lectura ONB02, ACT05, RET04, REC06</b><span>Segunda recarga, primera recarga o retorno en 14 días.</span></li>
      <li><span class="d">Día 30</span><b>Lectura XS03</b><span>Primera apuesta deportiva en 30 días.</span></li>
    </ol></div></section>
  <div class="g g2">
    <section class="panel"><div class="ph"><h2>Ejemplo con ACT01</h2><span class="sub">Escenario base (+25 %)</span></div><div class="pb">
      <div class="cmp">
        <div><span>Grupo envío</span><b>{EJ_ENV} jugadores</b><em>{EJ_ENV_C} recargan ({EJ_ENV_P})</em></div>
        <div><span>Grupo control</span><b>{EJ_CTL} jugadores</b><em>{EJ_CTL_C} recargan ({EJ_CTL_P})</em></div>
        <div class="hl"><span>Efecto del SMS</span><b>{EJ_DIF}</b><em>≈ {EJ_ADD} recargas que no habrían ocurrido</em></div>
      </div>
      <p class="small muted">Con estos tamaños, un efecto menor a ±{EJ_MDE} p.p. no se distingue del azar. Por eso las campañas pequeñas se leen como piloto.</p></div></section>
    <section class="panel"><div class="ph"><h2>Qué decidimos con el resultado</h2></div><div class="pb flush"><div class="list">
      <div class="li"><span class="ic ok">↑</span><div><b>Efecto positivo y mayor al mínimo detectable</b><span>Escalar: mantener la campaña y reducir el control al 10 %.</span></div><span></span></div>
      <div class="li"><span class="ic acc">=</span><div><b>Efecto positivo pero menor al mínimo detectable</b><span>Repetir una ola más y leer las dos juntas antes de decidir.</span></div><span></span></div>
      <div class="li"><span class="ic warn">↓</span><div><b>Sin efecto o negativo</b><span>Cambiar mensaje o momento; si se repite, apagar la campaña.</span></div><span></span></div>
      <div class="li"><span class="ic crit">!</span><div><b>Aumentan bajas, quejas o señales de juego responsable</b><span>Pausar de inmediato, sin esperar la lectura.</span></div><span></span></div>
    </div></div></section>
  </div>
  <section class="panel"><div class="ph"><h2>De dónde sale cada dato</h2></div><div class="pb flush"><div class="tw"><table class="wide"><thead><tr><th>Etapa</th><th>Indicador</th><th>Fuente</th><th>Estado</th></tr></thead><tbody>
    <tr><td>Envío y entrega</td><td>SMS enviados, entregados y rebotados por campaña y grupo</td><td>Proveedor SMS</td><td><span class="pill warn">Pendiente integración</span></td></tr>
    <tr><td>Clic</td><td>Clics únicos por enlace individual con UTM (<code>utm_source=sms&amp;utm_campaign=ACT01</code>)</td><td>Acortador con seguimiento</td><td><span class="pill warn">Por definir</span></td></tr>
    <tr><td>Acción</td><td>Recarga, apuesta o retorno en la ventana</td><td>Archivos diarios de YAjuego</td><td><span class="pill ok">Disponible</span></td></tr>
    <tr><td>Efecto</td><td>Tasa envío − tasa control, con intervalo de confianza</td><td>Vincero</td><td><span class="pill ok">Listo</span></td></tr>
  </tbody></table></div></div></section>
</section>

<section class="view" id="v-plan" data-title="Plan de ejecución">
  <div class="vhead"><div><h1>Plan de ejecución</h1><p>De hoy a la primera lectura de resultados en cinco semanas. Cada fila dice qué se entrega, quién lo hace y para cuándo.</p></div>
    <span class="chip acc">Próximo hito: validaciones de YAjuego · 27-nov</span></div>
  <section class="panel ask"><div class="ph"><h2>Lo que necesitamos de YAjuego esta semana</h2><span class="sub">Bloquea el primer envío</span></div><div class="pb flush"><div class="list">
    <div class="li"><span class="ic crit">1</span><div><b>Lista de consentimiento, autoexclusión y bloqueos</b><span>Cumplimiento · sin ella ninguna audiencia se activa</span></div><span class="pill crit">Bloqueante</span></div>
    <div class="li"><span class="ic crit">2</span><div><b>Aprobación de copies, leyenda +18 y texto de baja</b><span>Legal y CRM</span></div><span class="pill crit">Bloqueante</span></div>
    <div class="li"><span class="ic warn">3</span><div><b>Días faltantes con el export de solicitudes</b><span>Tecnología · casino 1-27 oct, 9-nov y deportes del 11 y 13-nov</span></div><span class="pill warn">Mejora segmentos</span></div>
    <div class="li"><span class="ic warn">4</span><div><b>Enlaces de destino, acortador con UTM y tarifa por SMS</b><span>CRM y proveedor SMS</span></div><span class="pill warn">Necesario para medir</span></div>
    <div class="li"><span class="ic acc">5</span><div><b>Significado de códigos de estado de cuenta y Live = 2</b><span>Tecnología</span></div><span class="pill neu">Validación</span></div>
  </div></div></section>
  <section class="panel"><div class="ph"><h2>Calendario</h2><span class="sub">Semanas de lunes a viernes · festivos: 8-dic y 25-dic</span></div><div class="pb flush"><div class="tw">
    <table class="gantt wide"><thead><tr><th>Entregable</th><th>Responsable</th><th>Hasta 20-nov</th><th>23-27 nov</th><th>30 nov-4 dic</th><th>9-11 dic</th><th>14-18 dic</th><th>21-24 dic</th><th>Ene</th></tr></thead><tbody>
      <tr><td>Base consolidada, controles y app</td><td>Vincero</td><td><i class="b ok">Hecho</i></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>Segmentos y audiencias al 18-nov</td><td>Vincero</td><td><i class="b ok">Hecho</i></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>Validaciones y lista de supresión</td><td>YAjuego</td><td></td><td><i class="b crit">Pendiente</i></td><td></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>Datos faltantes y datos hasta 29-nov</td><td>YAjuego · Tecnología</td><td></td><td><i class="b warn">Pendiente</i></td><td><i class="b warn">→</i></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>Recalcular corte y entregar audiencias finales</td><td>Vincero</td><td></td><td></td><td><i class="b acc">Programado</i></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>Carga en proveedor y envío de prueba interno</td><td>YAjuego · CRM</td><td></td><td></td><td><i class="b acc">Programado</i></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>Ola 1: ONB02, XS03, ACT05, RET04, REC06</td><td>YAjuego · CRM</td><td></td><td></td><td></td><td><i class="b acc">Envío mié-vie</i></td><td></td><td></td><td></td></tr>
      <tr><td>ACT01 diario (si hay carga diaria)</td><td>Vincero · Tecnología</td><td></td><td></td><td></td><td><i class="b acc">Inicio</i></td><td><i class="b acc">→</i></td><td><i class="b acc">→</i></td><td><i class="b acc">→</i></td></tr>
      <tr><td>Lectura a 7 días (ACT01) y entregas</td><td>Vincero</td><td></td><td></td><td></td><td></td><td><i class="b acc">Lectura</i></td><td></td><td></td></tr>
      <tr><td>Lectura a 14 días y decisión por campaña</td><td>Vincero · CRM</td><td></td><td></td><td></td><td></td><td></td><td><i class="b acc">Decisión</i></td><td></td></tr>
      <tr><td>Lectura XS03 (30 días) y ola 2</td><td>Vincero · CRM</td><td></td><td></td><td></td><td></td><td></td><td></td><td><i class="b acc">8-ene</i></td></tr>
      <tr><td>Carga diaria automática y tablero</td><td>Vincero · Tecnología</td><td></td><td></td><td></td><td></td><td></td><td></td><td><i class="b neu">Propuesto</i></td></tr>
    </tbody></table></div></div></section>
  <div class="g g3">
    <section class="panel"><div class="ph"><h2>Hito 1 · 4-dic</h2></div><div class="pb small">Audiencias finales cruzadas con la lista de supresión y aprobadas por cumplimiento. Sin esto no hay envío.</div></section>
    <section class="panel"><div class="ph"><h2>Hito 2 · 11-dic</h2></div><div class="pb small">Ola 1 enviada a {SMS} jugadores, con el control intacto y los envíos registrados.</div></section>
    <section class="panel"><div class="ph"><h2>Hito 3 · 24-dic</h2></div><div class="pb small">Resultado por campaña: escalar, repetir o apagar, según las reglas del módulo Medición.</div></section>
  </div>
  <section class="panel"><div class="ph"><h2>Cómo se actualizan los datos</h2><span class="sub">Cada vez que llegan archivos</span></div><div class="pb flush"><div class="list">
    <div class="li"><span class="ic acc">1</span><div><b>Enviar los Excel diarios o mensuales</b><span>Desde el export de solicitudes; las vistas de lista recortan filas.</span></div><span></span></div>
    <div class="li"><span class="ic acc">2</span><div><b>Vincero carga y recalcula</b><span>Los archivos repetidos se omiten y las correcciones reemplazan a la versión anterior.</span></div><span></span></div>
    <div class="li"><span class="ic acc">3</span><div><b>Controles en 0 fallas</b><span>Si algo no cuadra, se revisa antes de entregar audiencias.</span></div><span></span></div>
    <div class="li"><span class="ic acc">4</span><div><b>Audiencias nuevas</b><span>Se entregan después de cruzar la lista de supresión.</span></div><span></span></div>
  </div></div></section>
</section>
"""

JS = r"""
(function(){
  const DATA = JSON.parse(document.getElementById('app-data').textContent);
  const views = [...document.querySelectorAll('.view')];
  const links = [...document.querySelectorAll('.nav a')];
  const crumb = document.getElementById('crumb-view');
  // Las vistas usan id "v-<nombre>" para que el navegador no salte al ancla al cambiar de módulo.
  function show(id){
    if(!views.some(v => v.id === 'v-' + id)) id = 'inicio';
    views.forEach(v => v.hidden = v.id !== 'v-' + id);
    links.forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + id));
    const act = links.find(a => a.classList.contains('on'));
    if(act && window.matchMedia('(max-width: 860px)').matches){ const nv = act.closest('.side'); nv.scrollLeft = act.offsetLeft - 80; }
    const v = document.getElementById('v-' + id);
    crumb.textContent = v.dataset.title;
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  show(location.hash.slice(1) || 'inicio');

  // Gestor de campañas
  const items = [...document.querySelectorAll('.citem')];
  function selectCamp(code){
    items.forEach(b => b.setAttribute('aria-selected', b.dataset.c === code ? 'true' : 'false'));
    document.querySelectorAll('.cdet').forEach(d => d.hidden = d.dataset.c !== code);
  }
  items.forEach(b => b.addEventListener('click', () => selectCamp(b.dataset.c)));
  if(items.length) selectCamp(items[0].dataset.c);
  document.querySelectorAll('.vars').forEach(g => {
    const btns = [...g.querySelectorAll('button')];
    btns.forEach(b => b.addEventListener('click', () => {
      btns.forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
      g.closest('.cdet').querySelectorAll('.bubble-var').forEach(x => x.hidden = x.dataset.v !== b.dataset.v);
    }));
  });


  // Simulador de resultados de campañas
  const camps = DATA.camps;
  const nf = (x, d = 0) => Number(x).toLocaleString('es-CO', {maximumFractionDigits: d, minimumFractionDigits: d});
  const money = x => '$' + (x >= 1e6 ? nf(x / 1e6, 1) + ' millones' : nf(x));
  let lift = 0.25;
  const tarifa = document.getElementById('tarifa');
  const ESC = {0: 'ninguno', 0.1: 'conservador', 0.25: 'base', 0.5: 'optimista'};
  function sim(){
    const t = parseFloat(tarifa.value);
    let env = 0, ctl = 0, sin = 0, add = 0, monto = 0;
    const rows = camps.map(c => {
      const s0 = c.envio * c.base, s1 = c.envio * c.base * (1 + lift), a = s1 - s0, pp = c.base * lift * 100;
      env += c.envio; ctl += c.control; sin += s0; add += a; monto += a * c.ticket;
      const ok = c.mde !== null && pp >= c.mde;
      const cpa = (t > 0 && a > 0) ? money(c.envio * t / a) : '—';
      // Ficha de la campaña
      const det = document.querySelector(`.cdet[data-c="${c.c}"]`);
      if(det){
        det.querySelector('.esc-name').textContent = ESC[lift];
        det.querySelector('.r-sin').textContent = nf(s0);
        det.querySelector('.r-con').textContent = nf(s1);
        det.querySelector('.r-con-l').textContent = `${nf(c.base * (1 + lift) * 100, 1)} % de ${nf(c.envio)} SMS`;
        det.querySelector('.r-add').textContent = '+' + nf(a);
        det.querySelector('.r-add-l').textContent = `${c.accion} en ${c.vent} (+${nf(pp, 1)} p.p.)`;
        det.querySelector('.r-mon').textContent = money(a * c.ticket);
        det.querySelector('.r-medible').innerHTML = lift === 0 ? 'Sin efecto, el grupo envío y el control deberían comportarse igual.' :
          (ok ? `<span class="pill ok">Confirmable</span> el efecto del escenario (+${nf(pp, 1)} p.p.) supera el mínimo detectable (±${nf(c.mde, 1)} p.p.).`
              : `<span class="pill warn">No confirmable</span> el efecto del escenario (+${nf(pp, 1)} p.p.) es menor al mínimo detectable (±${nf(c.mde, 1)} p.p.); se lee como piloto.`);
      }
      return `<tr><td><b>${c.c}</b> ${c.t}</td><td>${c.obj}</td><td class="num">${nf(c.envio)}</td><td class="num">${nf(c.base * 100, 1)} %</td>
        <td class="num">${nf(s0)}</td><td class="num">${nf(s1)}</td><td class="num"><b>+${nf(a)}</b></td><td class="num">${money(a * c.ticket)}</td>
        <td class="num">${cpa}</td><td>${lift === 0 ? '—' : (ok ? '<span class="pill ok">Sí</span>' : '<span class="pill warn">Piloto</span>')}</td></tr>`;
    });
    document.getElementById('sim-body').innerHTML = rows.join('');
    document.getElementById('s-env').textContent = nf(env);
    document.getElementById('s-ctl').textContent = nf(ctl);
    document.getElementById('s-sin').textContent = nf(sin);
    document.getElementById('s-add').textContent = '+' + nf(add);
    document.getElementById('s-add-l').textContent = `Recargas o apuestas extra frente al grupo de control, en el escenario elegido. ≈ ${money(monto)} en recargas o apuestas.`;
    document.getElementById('s-cpa').textContent = (t > 0 && add > 0) ? money(env * t / add) : '—';
    document.getElementById('s-cost').textContent = t > 0 ? `La ola cuesta ${money(env * t)}; dividido entre lo que agrega el SMS.` : 'Escribe arriba la tarifa por SMS del proveedor para calcularlo.';
  }
  document.querySelectorAll('#esc button').forEach(b => b.addEventListener('click', () => {
    lift = parseFloat(b.dataset.l);
    document.querySelectorAll('#esc button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    sim();
  }));
  tarifa.addEventListener('input', sim);
  sim();

  // Constructor de audiencias (cubo agregado)
  const cubo = DATA.cubo;
  const fmt = n => n.toLocaleString('es-CO');
  const total = cubo.reduce((s, r) => s + r.n, 0);
  const dims = ['cv', 'nv', 'pm', 'pr', 'op'];
  function sel(dim){ return [...document.querySelectorAll(`[data-dim="${dim}"]:checked`)].map(i => i.value); }
  function calc(){
    const S = Object.fromEntries(dims.map(d => [d, new Set(sel(d))]));
    const soloCont = document.getElementById('f-cont').checked;
    const sinJR = document.getElementById('f-jr').checked;
    let n = 0, cont = 0, jr = 0, sinTel = 0;
    const counts = Object.fromEntries(dims.map(d => [d, {}]));
    for(const r of cubo){
      const okDims = dims.every(d => S[d].has(r[d]));
      if(okDims){
        if(r.jr) jr += r.n;
        if(!r.reg) sinTel += r.n;
      }
      const okC = (!soloCont || r.ec === 'contactable_pendiente_consentimiento') && (!sinJR || !r.jr);
      for(const d of dims){
        if(okC && dims.every(o => o === d || S[o].has(r[o]))) counts[d][r[d]] = (counts[d][r[d]] || 0) + r.n;
      }
      if(okDims && okC){ n += r.n; if(r.ec === 'contactable_pendiente_consentimiento') cont += r.n; }
    }
    document.getElementById('ab-n').textContent = fmt(n);
    document.getElementById('ab-pct').textContent = (100 * n / total).toLocaleString('es-CO', {maximumFractionDigits: 1}) + ' % de ' + fmt(total) + ' jugadores';
    document.getElementById('ab-bar').style.width = (100 * n / total) + '%';
    document.getElementById('ab-cont').textContent = fmt(cont);
    document.getElementById('ab-ctrl').textContent = fmt(Math.round(cont * .2));
    document.getElementById('ab-env').textContent = fmt(cont - Math.round(cont * .2));
    document.getElementById('ab-jr').textContent = fmt(jr);
    document.getElementById('ab-tel').textContent = fmt(sinTel);
    document.querySelectorAll('[data-dim]').forEach(i => {
      const c = i.closest('label').querySelector('.ct');
      if(c) c.textContent = fmt(counts[i.dataset.dim][i.value] || 0);
    });
  }
  document.querySelectorAll('#builder input').forEach(i => i.addEventListener('change', calc));
  document.getElementById('ab-reset').addEventListener('click', () => {
    document.querySelectorAll('#builder [data-dim]').forEach(i => i.checked = true);
    document.getElementById('f-cont').checked = true; document.getElementById('f-jr').checked = true; calc();
  });
  calc();

  // Diccionario con búsqueda
  const dicc = DATA.dicc || [], tb = document.getElementById('dicc-body'), q = document.getElementById('dicc-q');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  if (tb && q) {
  let tabla = 'todas';
  function renderDicc(){
    const t = q.value.trim().toLowerCase();
    const rows = dicc.filter(r => (tabla === 'todas' || r.tabla.startsWith(tabla)) &&
      (!t || (r.campo + ' ' + r.definicion + ' ' + r.origen).toLowerCase().includes(t)));
    tb.innerHTML = rows.slice(0, 400).map(r => `<tr><td><code>${esc(r.tabla)}</code></td><td><code>${esc(r.campo)}</code></td><td class="mono small">${esc(r.tipo)}</td><td>${esc(r.definicion)}</td><td class="small muted">${esc(r.origen)}</td><td class="small muted">${esc(r.formula)}</td></tr>`).join('')
      || '<tr><td colspan="6" class="muted">Ningún campo coincide con la búsqueda. Prueba con otro término o con "todas".</td></tr>';
    document.getElementById('dicc-n').textContent = rows.length + ' campos';
  }
  q.addEventListener('input', renderDicc);
  document.querySelectorAll('#dicc-tabs button').forEach(b => b.addEventListener('click', () => {
    tabla = b.dataset.t;
    document.querySelectorAll('#dicc-tabs button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    renderDicc();
  }));
  renderDicc();
  }

  // Controles con filtro
  const cb = document.getElementById('ctrl-body');
  if (cb) {
  function renderCtrl(f){
    const rows = DATA.ctrl.filter(r => f === 'todos' || r.estado === f);
    const cls = {OK: 'ok', FALLA: 'crit', INFO: 'neu'};
    cb.innerHTML = rows.map(r => `<tr><td>${esc(r.control)}</td><td class="num">${esc(r.esperado)}</td><td class="num">${esc(r.obtenido)}</td><td><span class="pill ${cls[r.estado]}">${esc(r.estado)}</span></td><td class="small muted">${esc(r.nota || '')}</td></tr>`).join('');
  }
  document.querySelectorAll('#ctrl-tabs button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#ctrl-tabs button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    renderCtrl(b.dataset.f);
  }));
  renderCtrl('todos');
  }
})();
"""
NOMBRES_CV = {"1_nuevo_sin_actividad": "Nuevo sin actividad", "2_nuevo_en_activacion": "Nuevo en activación",
              "3_activo": "Activo (≤ 14 días)", "4_enfriandose": "Enfriándose (15-30 días)",
              "5_inactivo_31_60": "Inactivo 31-60 días", "6_inactivo_61_mas": "Inactivo 61+ días",
              "7_sin_actividad_de_juego_observada": "Sin juego observado"}
NOMBRES_NV = {"sin_recarga": "Sin recarga", "bajo": "Bajo (< p50)", "medio": "Medio (p50-p90)", "alto": "Alto (≥ p90)"}
NOMBRES_PR = {"abandono_alta": "Riesgo de abandono alto", "abandono_media": "Riesgo de abandono medio",
              "abandono_baja": "Riesgo de abandono bajo", "activacion_alta": "Prob. de activarse alta",
              "activacion_media": "Prob. de activarse media", "activacion_baja": "Prob. de activarse baja",
              "sin_prediccion": "Sin predicción"}
NOMBRES_OP = {"habito": "Oportunidad: volverse habitual", "cruzada_deportes": "Oportunidad: deportes",
              "modalidad": "Oportunidad: otra modalidad", "sin_oportunidad": "Sin oportunidad destacada"}
NOMBRES_PM = {"insuficiente": "Menos de 5 apuestas", "prepartido": "Prepartido", "en_vivo": "En vivo", "mixto": "Mixto"}


def insight(titulo, metrica, metrica_lbl, obs, evid, interp, accion, chart="", tag=""):
    return f"""<section class="panel">
  <div class="ph"><h2>{titulo}</h2>{tag}</div>
  <div class="ins{'' if chart else ' one'}">
    <div class="txt">
      <div class="metric"><b>{metrica}</b><span>{metrica_lbl}</span></div>
      <p class="small">{interp}</p>
      <div class="todo"><b>Qué hacer</b><span>{accion}</span></div>
      <details class="how"><summary>Ver detalle</summary><p class="small">{obs}</p><p class="small" style="margin-top:6px">{evid}</p></details>
    </div>
    {f'<div class="fig">{chart}</div>' if chart else ''}
  </div>
</section>"""


def info(tip):
    return f'<span class="info" tabindex="0" role="note" aria-label="{esc(tip)}" data-tip="{esc(tip)}">i</span>' if tip else ""


def tile(lab, val, ft, acc=False, tip=None):
    return f'<div class="tile{" acc" if acc else ""}"><div class="lab">{lab}{info(tip)}</div><div class="val">{val}</div><div class="ft">{ft}</div></div>'


def construir_html(D):
    import json
    import numpy as np
    corte = pd.Timestamp(D["corte"])
    fin = pd.Timestamp(D["fin_analisis"])
    cob = D["cob"]
    reg_tot, hist = cob.loc[True], cob.loc[False]
    pct_apu_hist = 100 * hist.am / (hist.am + reg_tot.am)
    emb = D["emb"]
    conv_tot = 100 * emb.con_recarga.sum() / emb.registrados.sum()
    t1 = D["t1"].set_index("tramo")
    pct_1h = 100 * t1.loc["1. < 1 hora", "jugadores"] / t1.jugadores.sum()
    pct_24h = 100 * (t1.loc["1. < 1 hora", "jugadores"] + t1.loc["2. 1-24 horas", "jugadores"]) / t1.jugadores.sum()
    conc = D["conc"].set_index(["medida", "top_pct_jugadores"]).pct_del_monto
    ret = D["retencion"].set_index("cohorte_registro")
    ret_pct = 100 * ret.act_v1 / ret.conv.where(ret.conv > 0)
    MES_N = {"2026-07": "julio", "2026-08": "agosto", "2026-09": "septiembre", "2026-10": "octubre",
             "2026-11": "noviembre", "2026-12": "diciembre", "2027-01": "enero"}
    coh = list(emb.cohorte_registro)
    coh_ult = coh[-1]  # cohorte del mes del corte: todavía en curso
    emb_i = emb.set_index("cohorte_registro")
    conv_txt = ", ".join(f"{MES_N.get(c, c)} {n(emb_i.loc[c, 'pct_recarga'], 1)} %" for c in coh) + " (en curso)"
    rep_cerr = emb_i.loc[[c for c in coh if c != coh_ult], "pct_repite_de_convertidos"].dropna()
    repite_txt = f"{n(rep_cerr.min(), 0)}-{n(rep_cerr.max(), 0)} %" if len(rep_cerr) > 1 else (f"{n(rep_cerr.iloc[0], 0)} %" if len(rep_cerr) else "—")
    ret_txt = ", ".join(f"{MES_N.get(c, c)} {n(ret_pct[c], 0)} %" for c in coh if c != coh_ult and pd.notna(ret_pct.get(c)))
    ret_ini = ret_pct.get(coh[0])
    rsa_pct = 100 * D["rsa"].sin / D["rsa"].con
    rsa_m = 100 * D["rsa_monto"].a / D["rsa_monto"].b
    mes, mix, cam, hip, P = D["mes"], D["mix"], D["cam"], D["hip"], D["params"]
    # Cifras que antes eran fijas: ahora salen de la base en cada corrida.
    vf = D["verif"].set_index("c").p
    mx = mix.set_index("tipo")
    sv, cpp = mx.loc["Simple · en vivo"], mx.loc["Combinada/sistema · prepartido"]
    ta = D["tasas"]
    t_sim = pd.Timestamp(D["t_sim"])

    def tasa(c):
        return (float(ta.loc[c, "tasa"]), f"{n(100 * ta.loc[c, 'tasa'], 1)} %") if c in ta.index else (0.0, "—")
    CF = {"tasa_act01": tasa("ACT01"), "tasa_act05": tasa("ACT05"), "tasa_onb02": tasa("ONB02"), "tasa_xs03": tasa("XS03"),
          "tasa_ret04": tasa("RET04"), "tasa_rec06": tasa("REC06"),
          "verif_si": f"{n(100 * vf.get(30, 0), 1)} %", "verif_no": f"{n(100 * vf.get(20, 0), 1)} %",
          "conv_cohortes": conv_txt, "repite": repite_txt,
          "vivo_monto": f"{n(sv.pct_monto, 0)} %", "vivo_apuestas": f"{n(sv.pct_apuestas, 0)} %", "vivo_mediana": cop(sv.apuesta_mediana),
          "comb_apuestas": f"{n(cpp.pct_apuestas, 0)} %", "comb_mediana": cop(cpp.apuesta_mediana), "comb_sel": n(cpp.selecciones_mediana),
          "recarga_mediana": cop(D["rec_med"]), "cop_eur": f"~{n(D['cop_eur'])}"}
    fallas = int(D["controles"].set_index("estado").n.get("FALLA", 0))
    n_ctrl = int(D["controles"].n.sum())
    dow = D["dow"].set_index("d").x
    res = D["res"]
    hold = 100 * (res.ap - res.pg) / res.ap
    h = D["hist"]
    rec, apu, retd = D["rec"], D["apu"], D["ret"]
    tel = D["telef"]
    cv = D["cv"]
    rc = D["rc"]
    logo_w = b64(ASSETS / "vincero_logo_white.png")
    mark_b = b64(ASSETS / "vincero_mark_black.png")

    # ---------- gráficos ----------
    f_emb = bars_v([MES_N.get(c, c).capitalize() + (" (en curso)" if c == coh_ult else "") for c in emb.cohorte_registro],
                   [("Recargó", list(emb.pct_recarga), "--s1"), ("Apostó en deportes", list(emb.pct_apuesta), "--s2")],
                   fmt=lambda v: f"{n(v, 1)} %", sub=[f"{n(x)} registros" for x in emb.registrados])
    f_t1 = bars_v([s[3:] for s in D["t1"].tramo], [("% de quienes recargaron", list(D["t1"].pct), "--s2")],
                  fmt=lambda v: f"{n(v, 0)} %", sub=[f"{n(x)} jugadores" for x in D["t1"].jugadores])
    f_rc = bars_v([f"{t} días" for t in rc.tramo_dias],
                  [("Base anterior a julio (sin teléfono)", list(rc.sin_datos_contacto), "--s1"),
                   ("Registrados desde julio (con teléfono)", list(rc.con_datos_contacto), "--s2")])
    curvas = []
    for col, nombre, var in [("apu_monto", "Monto apostado", "--s1"), ("rec_monto", "Monto recargado", "--s2")]:
        v = np.sort(D["lor"][col].astype(float).values)[::-1]
        acum = np.cumsum(v) / v.sum() * 100
        idx = np.unique(np.linspace(0, len(v) - 1, 600).astype(int))
        curvas.append((nombre, [0] + list((idx + 1) / len(v) * 100), [0] + list(acum[idx]), var,
                       [(p, conc[(nombre, p)]) for p in (1, 10)]))
    f_lor = lorenz(curvas)
    f_mix = bars_h(list(mix.tipo), [("% de apuestas", list(mix.pct_apuestas), "--s1"), ("% del monto apostado", list(mix.pct_monto), "--s2")],
                   fmt=lambda v: f"{n(v, 0)} %", lab_w=230)
    f_hm = heatmap(D["hm"])
    f_dia = lines_small(D["dia"], ["apuestas", "recargas"], ["Apuestas deportivas por día", "Recargas por día"])
    f_cv = bars_h([NOMBRES_CV[c] for c in cv.ciclo_vida],
                  [("Contactable con los datos recibidos", list(cv.contactables), "--s2"),
                   ("No contactable", list(cv.total - cv.contactables), "--s1")],
                  stacked=True, total_lbl=[f"{n(t)} ({n(100 * t / cv.total.sum(), 1)} %)" for t in cv.total], w=1100, lab_w=200, row=40, pad_r=150)

    # ---------- jugadores ----------
    pf = D["perfil"]
    tot_j = int(pf.j.sum())
    filas_pf = []
    for r in pf.itertuples():
        filas_pf.append(dict(pob="Registrados desde julio" if r.reg else "Base anterior a julio",
                             act=f"<strong>{r.act}</strong>", j=n(r.j), p=f"{n(100 * r.j / tot_j, 1)} %",
                             ret=n(r.con_retiro), rec=n(r.rec), recm=mm(r.recm) if r.recm else "—",
                             apu=n(r.apu), apum=mm(r.apum) if r.apum else "—", retm=mm(r.retm) if r.retm else "—",
                             mr=n(r.med_rec), ma=n(r.med_apu), md=n(r.med_dias)))
    t_pf = table(pd.DataFrame(filas_pf), [("pob", "Población"), ("act", "Actividad desde el 1-jul"), ("j", "Jugadores"), ("p", "%"),
                                          ("rec", "Recargas"), ("recm", "Recargado"), ("apu", "Apuestas"), ("apum", "Apostado"),
                                          ("ret", "Con retiro"), ("retm", "Retirado"), ("mr", "Recargas (mediana)"),
                                          ("ma", "Apuestas (mediana)"), ("md", "Días activos (mediana)")],
                 num=("j", "p", "rec", "recm", "apu", "apum", "ret", "retm", "mr", "ma", "md"), cls="wide")
    orden = ["Recarga y apuesta", "Solo recarga", "Solo apuesta", "Sin recarga ni apuesta"]
    piv = pf.pivot_table(index="act", columns="reg", values="j", aggfunc="sum").reindex(orden).fillna(0)
    f_pf = bars_h(orden, [("Registrados desde julio", list(piv.get(True, [0] * 4)), "--s2"),
                          ("Base anterior a julio", list(piv.get(False, [0] * 4)), "--s1")],
                  stacked=True, total_lbl=[f"{n(t)} ({n(100 * t / tot_j, 1)} %)" for t in piv.sum(axis=1)], w=1100, lab_w=170, row=40, pad_r=150)
    ia, ir = D["int_apu"], D["int_rec"]
    f_ia = bars_v(list(ia.b), [("% del monto apostado", list(ia.pm), "--s2")], fmt=lambda v: f"{n(v, 0)} %",
                  sub=[f"{n(x)} jugadores" for x in ia.j])
    f_ir = bars_v(list(ir.b), [("% del monto recargado", list(ir.pm), "--s2")], fmt=lambda v: f"{n(v, 0)} %",
                  sub=[f"{n(x)} jugadores" for x in ir.j])
    nuevos_sin = int(pf[(pf.reg) & (pf.act == "Sin recarga ni apuesta")].j.sum())
    activos_rec_apu = int(pf[pf.act == "Recarga y apuesta"].j.sum())

    # ---------- tendencias y casino (toda la base) ----------
    cas = D["cas"]
    f_cas_prov = bars_h(list(D["cas_prov"].proveedor.str.replace("_", " ").str.title()),
                        [("% del monto apostado en casino", list(D["cas_prov"].pm), "--s2")], fmt=lambda v: f"{n(v, 1)} %", lab_w=150)
    ch = D["cas_hora"].set_index("h").reindex(range(24), fill_value=0)
    f_cas_hora = bars_v([f"{h}h" if h % 3 == 0 else "" for h in range(24)], [("Rondas de casino", list(ch.n), "--s2")],
                        fmt=lambda v: n(v / 1000, 0) + " mil" if v >= 1000 else n(v), h=230, labels=False)
    hc = D["hip_cas"]
    pct_sr_cas = 100 * hc.sin_dep_cas / hc.sin_dep if hc.sin_dep else 0
    MESES = {7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}
    DIAS_SEM = {1: "lun", 2: "mar", 3: "mié", 4: "jue", 5: "vie", 6: "sáb", 7: "dom"}
    # Festivos de Colombia en el periodo (Ley Emiliani): cambian el patrón frente a una semana normal.
    FESTIVOS = {pd.Timestamp(x).date() for x in ("2026-07-20", "2026-08-07", "2026-08-17", "2026-10-12", "2026-11-02",
                                                 "2026-11-16", "2026-12-08", "2026-12-25")}
    fd = lambda d: f"{d.day}-{MESES.get(d.month, d.month)}"  # noqa: E731

    # Cobertura por día y fuente (meta.cobertura_dia): completo, parcial o falta.
    FUENTES = ["registros", "recargas", "apuestas", "casino", "retiros"]
    cobx = D["cobertura"].copy()
    cobx["dia"] = pd.to_datetime(cobx.dia).dt.date
    estado = {(r.dia, r.fuente): r.estado for r in cobx.itertuples()}
    rango = sorted(cobx.dia.unique())
    cas_d0, cas_d1 = pd.Timestamp(cas.d0).date(), pd.Timestamp(cas.d1).date()
    con_datos = [d for d in rango if any(estado[(d, f)] != "falta" for f in FUENTES)]
    ultimo = max(con_datos) if con_datos else corte.date()
    dias_sin = [d for d in rango if d not in con_datos]
    n_rec = sum(v == "parcial" for v in estado.values())
    dias_cas = sum(estado[(d, "casino")] == "completo" for d in rango)
    sin_txt = (", ".join(fd(d) for d in dias_sin[:-1]) + (" y " if len(dias_sin) > 1 else "") + fd(dias_sin[-1])) if dias_sin else ""
    faltan_dep = [d for d in rango if estado[(d, "apuestas")] == "falta" and d not in dias_sin]
    dep_txt = (", ".join(fd(d) for d in faltan_dep[:-1]) + (" y " if len(faltan_dep) > 1 else "") + fd(faltan_dep[-1])) if faltan_dep else ""
    periodo_txt = f"del {fd(rango[0])} al {fd(ultimo)}" if rango else "—"
    cas_txt = f"{dias_cas} días con casino, del {fd(cas_d0)} al {fd(cas_d1)}"
    df_dia = D["dia_fuente"].copy()
    df_dia["d"] = pd.to_datetime(df_dia.d).dt.date
    cnt = df_dia.set_index(["d", "fuente"])

    def tot(fuente, campo="m"):
        """Suma en toda la base (incluye días parciales)."""
        x = df_dia[df_dia.fuente == fuente][campo]
        return float(np.nansum(x)) if len(x) else 0.0
    dias_ambos = [d for d in rango if estado[(d, "casino")] == "completo" and estado[(d, "apuestas")] == "completo"]
    dep_mismos = sum(cnt.loc[(d, "apuestas")].m for d in dias_ambos if (d, "apuestas") in cnt.index)
    cas_mismos = sum(cnt.loc[(d, "casino")].m for d in dias_ambos if (d, "casino") in cnt.index)
    cb = D["cas_base"].set_index("g").n

    # Tendencia semanal: promedio por día completo de cada producto, en toda la base.
    semanas = {}
    for d in rango:
        semanas.setdefault(d - pd.Timedelta(days=d.weekday()), []).append(d)
    filas_sem, serie = [], []
    prev = {}
    for lunes, ds in semanas.items():
        fila, punto = {"sem": f'<span style="white-space:nowrap">{fd(ds[0])} al {fd(ds[-1])}</span>'
                              + (' <span class="muted small">· festivo</span>' if any(d in FESTIVOS for d in ds) else '')}, {"dia": lunes}
        for f, k in [("apuestas", "dep"), ("recargas", "rec"), ("casino", "cas")]:
            ok = [d for d in ds if estado[(d, f)] == "completo" and (d, f) in cnt.index]
            prom = sum(cnt.loc[(d, f)].m for d in ok) / len(ok) if ok else None
            punto[k] = prom if prom is not None else np.nan
            fila[k] = ((mm(prom) + (f' <span class="muted small">· {len(ok)} de {len(ds)} días</span>' if len(ok) < len(ds) else "")) if ok else "—")
            ant = prev.get(k)
            fila[k + "_v"] = (f"{'+' if prom >= ant else ''}{n(100 * (prom / ant - 1), 0)} %" if (prom and ant) else "—")
            if prom:
                prev[k] = prom
        filas_sem.append(fila)
        serie.append(punto)
    t_pd = table(pd.DataFrame(filas_sem[::-1]), [("sem", "Semana"), ("dep", "Deportes: apostado por día"), ("dep_v", "vs sem. ant."),
                                                 ("rec", "Recargado por día"), ("rec_v", "vs sem. ant."),
                                                 ("cas", "Casino: apostado por día"), ("cas_v", "vs sem. ant.")],
                 num=("dep", "dep_v", "rec", "rec_v", "cas", "cas_v"), cls="wide")
    f_sem = lines_small(pd.DataFrame(serie), ["dep", "rec", "cas"],
                        ["Deportes: apostado por día (promedio semanal)", "Recargado por día (promedio semanal)", "Casino: apostado por día (promedio semanal)"],
                        w=1100, h=150, fmt=lambda v: mm(v), sabados=False, tip=lambda d: f"semana del {d:%d-%m}", pl=120)

    # ---------- tablas ----------
    man = D["manifiesto"].copy()
    fuente_lbl = {"apuestas": "Apuestas deportivas", "recargas": "Recargas", "registros": "Registros", "retiros": "Retiros"}
    man["fuente"] = man.fuente.map(fuente_lbl).fillna("—")
    # Quita el prefijo de carga ("1a2b3c4d-") cuando existe; los archivos del zip no lo traen.
    man["archivo"] = man.archivo.map(lambda a: f"<code>{esc(re.sub(r'^[0-9a-f]{8}-', '', a))}</code>")
    man["periodo"] = [f"{a:%d-%m-%Y} → {b:%d-%m-%Y}" if pd.notna(a) else "—" for a, b in zip(man.periodo_min, man.periodo_max)]
    man["filas"] = man.filas.map(lambda x: n(x) if pd.notna(x) else "—")
    man["estado"] = man.estado.map({"cargado": '<span class="pill ok">Cargado</span>',
                                    "duplicado_exacto": '<span class="pill warn">Copia idéntica · omitido</span>',
                                    "reemplazado": '<span class="pill neu">Reemplazado</span>'})
    t_man = table(man, [("fuente", "Fuente"), ("archivo", "Archivo"), ("filas", "Filas"), ("periodo", "Periodo según contenido"), ("estado", "Estado")], num=("filas",))

    mes_t = mes.copy()
    mes_t["mes"] = [MES_N.get(m, m).capitalize() + (f' <span class="muted small">· hasta el {fd(ultimo)}</span>' if d < pd.Period(m).days_in_month else "")
                    for m, d in zip(mes_t.mes, mes_t.dias)]
    for c in ["registros_dia", "recargas_dia", "apuestas_dia", "jugadores_recarga", "apostadores", "dias"]:
        mes_t[c] = mes_t[c].map(n)
    for c in ["monto_recargas_dia", "monto_apostado_dia", "monto_casino_dia", "monto_retiros_dia"]:
        mes_t[c] = mes_t[c].map(lambda x: f"${n(x / 1e6, 0)} millones" if pd.notna(x) else "—")
    t_mes = table(mes_t, [("mes", "Mes"), ("dias", "Días"), ("registros_dia", "Registros/día"), ("recargas_dia", "Recargas/día"),
                          ("monto_recargas_dia", "Recargado/día"), ("jugadores_recarga", "Jugadores que recargan"),
                          ("apuestas_dia", "Apuestas/día"), ("monto_apostado_dia", "Apostado/día"), ("apostadores", "Apostadores"),
                          ("monto_casino_dia", "Casino/día"), ("monto_retiros_dia", "Retiros netos/día")],
                  num=("dias", "registros_dia", "recargas_dia", "monto_recargas_dia", "jugadores_recarga", "apuestas_dia",
                       "monto_apostado_dia", "apostadores", "monto_casino_dia", "monto_retiros_dia"), cls="wide")
    met = D["met"].copy()
    met["pct_recargas"] = met.pct_recargas.map(lambda x: f"{n(x, 1)} %")
    met["recarga_mediana"] = met.recarga_mediana.map(cop)
    met["monto"] = met.monto.map(mm)
    met["recargas"] = met.recargas.map(n)
    met["jugadores"] = met.jugadores.map(n)
    t_met = table(met, [("metodo", "Medio"), ("recargas", "Recargas"), ("pct_recargas", "% recargas"), ("monto", "Monto"),
                        ("recarga_mediana", "Recarga mediana"), ("jugadores", "Jugadores")],
                  num=("recargas", "pct_recargas", "monto", "recarga_mediana", "jugadores"))

    # ---------- segmentos ----------
    seg_def = [
        ("1_nuevo_sin_actividad", "Registrado desde el 1-jul, sin recargas ni apuestas",
         f"{n(pct_24h, 0)} % de quienes convierten lo hacen en 24 h; después de 7 días la conversión natural es {CF['tasa_act05'][1]}.",
         "ACT01 y ACT05: explicar cómo recargar", "Diaria", "Alta en la regla, media en el efecto"),
        ("2_nuevo_en_activacion", "Registrado desde el 1-jul; primera actividad en los últimos 30 días",
         f"{CF['repite']} de los convertidos hace una segunda recarga.", "ONB02: lograr la segunda recarga", "Semanal", "Alta"),
        ("3_activo", f"Última recarga, apuesta o ronda de casino hace ≤ {int(P['dias_activo_max'])} días",
         f"14 días ≈ p85 del intervalo entre días de apuesta. {n(100 * (1 - cv.set_index('ciclo_vida').loc['3_activo'].contactables / cv.set_index('ciclo_vida').loc['3_activo'].total), 0)} % sin teléfono en los archivos.", "Solo mensajes de servicio", "Semanal", "Alta"),
        ("4_enfriandose", f"Última actividad hace {int(P['dias_activo_max']) + 1}-{int(P['dias_enfriando_max'])} días",
         f"{CF['tasa_ret04'][1]} vuelve solo en 14 días (corte simulado al {fd(t_sim)}).", "RET04: recordatorio con agenda deportiva", "Semanal", "Media: falta casino 1-27 oct"),
        ("5_inactivo_31_60", "Última actividad hace 31-60 días", f"{CF['tasa_rec06'][1]} vuelve solo en 14 días.", "REC06: recuperar según su preferencia", "Mensual", "Media: falta casino 1-27 oct"),
        ("6_inactivo_61_mas", "Última actividad hace más de 60 días", "Puede incluir a quien solo jugó casino antes del 28-oct (sin datos de casino).", "No contactar por ahora", "Mensual", "Baja"),
        ("7_sin_actividad_de_juego_observada", "Solo aparece en Retiros", "Retiró sin recargar ni apostar en deportes.", "Ninguna", "Mensual", "Baja"),
    ]
    cvi = cv.set_index("ciclo_vida")
    filas_seg = [dict(nombre=f"<strong>{NOMBRES_CV[c]}</strong>{info(f'{r}. {comp} Confianza: {conf.lower()}.')}",
                      tam=f"{n(cvi.loc[c].total)} <span class='muted small'>· {n(100 * cvi.loc[c].total / cv.total.sum(), 0)} %</span>",
                      cont=n(cvi.loc[c].contactables), obj=obj, act=act)
                 for c, r, comp, obj, act, conf in seg_def]
    t_seg = table(pd.DataFrame(filas_seg), [("nombre", "Segmento"), ("tam", "Jugadores"), ("cont", "Contactables"),
                                            ("obj", "Qué hacer"), ("act", "Se actualiza")],
                  num=("tam", "cont"))
    hip_def = [
        ("h_sin_recarga_0_7d", "Sin recarga, 0-7 días", "Historia completa, sin recargas ni apuestas, no depositante, antigüedad ≤ 7 días", "ACT01"),
        ("h_sin_recarga_8_30d", "Sin recarga, 8-30 días", "Ídem con antigüedad 8-30 días", "ACT05"),
        ("h_sin_recarga_31d_mas", "Sin recarga, 30+ días", "Ídem con antigüedad > 30 días", "Sin campaña"),
        ("h_deposito_posterior_al_corte", "Depositó después del corte", "Sin recargas en la ventana pero marcado depositante", "Exclusión"),
        ("h_una_sola_recarga", "Una sola recarga", "Historia completa, 1 recarga hace ≥ 7 días", "ONB02"),
        ("h_recarga_sin_apuesta_deportiva", "Recargó sin apostar en deportes", "rec_n > 0 y apu_n = 0", "XS03"),
        ("h_atrasado_vs_ritmo_propio", "Atrasado frente a su ritmo", "≥ 3 días activos, 8-30 días sin actividad y > 2 × su intervalo habitual", "RET04"),
        ("h_retorno", "Retorno", "Activo, inactivo y de nuevo activo en ventanas de 30 días", "Analítico"),
        ("h_continuo_3_ventanas", "Continuo", "Activo en las tres ventanas de 30 días", "Analítico"),
        ("h_caida_de_frecuencia", "Caída de frecuencia", "Días con apuesta en v1 ≤ 50 % de su promedio previo", "Ninguna (posible autorregulación)"),
        ("senal_revision_juego_responsable", "Señal de revisión JR", f"≥ {int(P['rec_max_dia_p99'])} recargas en un día, ≥ 50 % de madrugada, o escalada ≥ 3× sobre p90", "Exclusión total"),
    ]
    filas_h = [dict(nom=f"<strong>{nm}</strong>", regla=r, j=n(hip.loc[k].jugadores), p=f"{n(hip.loc[k].pct_poblacion, 1)} %",
                    c=n(hip.loc[k].contactables), uso=f"<code>{u}</code>" if u[:3].isupper() else u) for k, nm, r, u in hip_def]
    t_hip = table(pd.DataFrame(filas_h), [("nom", "Etiqueta"), ("regla", "Regla"), ("j", "Jugadores"), ("p", "% pobl."),
                                          ("c", "Contactables"), ("uso", "Uso")], num=("j", "p", "c"), cls="wide")

    # ---------- constructor de audiencias ----------
    cubo = D["cubo"]

    def checks(dim, nombres, orden):
        return "".join(f'<label><input type="checkbox" data-dim="{dim}" value="{k}" checked> {nombres[k]}<span class="ct"></span></label>'
                       for k in orden if k in set(cubo[dim]))
    ck_cv = checks("cv", NOMBRES_CV, list(NOMBRES_CV))
    ck_nv = checks("nv", NOMBRES_NV, ["sin_recarga", "bajo", "medio", "alto"])
    ck_pm = checks("pm", NOMBRES_PM, ["insuficiente", "prepartido", "en_vivo", "mixto"])
    ck_pr = checks("pr", NOMBRES_PR, list(NOMBRES_PR))
    ck_op = checks("op", NOMBRES_OP, list(NOMBRES_OP))

    # ---------- campañas ----------
    BASE = {
        "ACT01": (CF["tasa_act01"][0], f"{CF['tasa_act01'][1]} recarga entre el día 1 y el 8 tras registrarse"),
        "ACT05": (CF["tasa_act05"][0], f"{CF['tasa_act05'][1]} recarga entre el día 7 y el 21"),
        "ONB02": (CF["tasa_onb02"][0], f"{CF['tasa_onb02'][1]} vuelve a recargar en 14 días"),
        "XS03": (CF["tasa_xs03"][0], f"{CF['tasa_xs03'][1]} hace su primera apuesta deportiva en el mes siguiente"),
        "RET04": (CF["tasa_ret04"][0], f"{CF['tasa_ret04'][1]} vuelve en 14 días según su recencia"),
        "REC06": (CF["tasa_rec06"][0], f"{CF['tasa_rec06'][1]} vuelve en 14 días"),
    }
    camp_def = [
        dict(c="ACT01", t="Activación temprana", tipo="Tiempo real recomendado",
             hall=f"El {n(pct_1h, 0)} % de quienes recargan lo hace en la primera hora y el {n(pct_24h, 0)} % en 24 h.",
             seg="Sin recarga, 0-7 días de registro", regla="historia_completa AND rec_n = 0 AND apu_n = 0 AND depositante = 0 AND antigüedad ≤ 7 d",
             obj="Primera recarga", momento="24 h después del registro si no hay recarga (requiere carga diaria)",
             salida="Primera recarga o día 8", kpi="Primera recarga en 7 días", vent="7 días",
             datos="Export diario de registros y recargas"),
        dict(c="ONB02", t="Segunda recarga", tipo="Lote semanal",
             hall=f"{CF['repite']} de los nuevos que recargan repite. De los convertidos de {MES_N.get(coh[0], coh[0])}, solo {n(ret_ini, 0)} % sigue activo en los últimos 30 días.",
             seg="Una sola recarga, 7+ días sin actividad", regla="historia_completa AND rec_n = 1 AND primera_recarga ≤ corte − 7 d AND inactivo ≥ 7 d",
             obj="Segunda recarga", momento="Martes a jueves, en su franja habitual", salida="Segunda recarga",
             kpi="Segunda recarga en 14 días", vent="14 días", datos="Recargas posteriores al envío"),
        dict(c="XS03", t="Primera apuesta deportiva", tipo="Lote semanal",
             hall=f"{n(rsa_pct, 0)} % de los registrados que recargaron nunca apostó en deportes.",
             seg="Recargó sin apostar en deportes (registrados desde julio)", regla="rec_n > 0 AND apu_n = 0 AND historia_completa AND última_recarga ≤ 60 d",
             obj="Primera apuesta deportiva", momento="Jueves o viernes previo a fecha de fútbol", salida="Primera apuesta deportiva",
             kpi="Primera apuesta deportiva en 30 días", vent="30 días", datos="Actividad de casino para excluir activos allí"),
        dict(c="RET04", t="Pre-abandono según su ritmo", tipo="Lote semanal",
             hall=f"Intervalo típico entre días de apuesta: {n(D['intervalo'].med)} días (p90: {n(D['intervalo'].p90)}). Quien duplica su intervalo se está alejando.",
             seg="Atrasado frente a su ritmo, 8-30 días", regla="días_activos ≥ 3 AND inactivo 8-30 d AND inactivo > 2 × max(intervalo_propio, 3)",
             obj="Volver a apostar", momento="Semanal; variante en vivo o prepartido", salida="Nueva actividad",
             kpi="Retorno en 14 días", vent="14 días", datos=f"Teléfonos de la base histórica (+{n(h.atrasado)} jugadores)"),
        dict(c="ACT05", t="Recordatorio de activación", tipo="Lote semanal",
             hall=f"Conversión natural tras el día 7: {CF['tasa_act05'][1]}. Población grande; el control dirá si el SMS paga su costo.",
             seg="Sin recarga, 8-30 días de registro", regla="historia_completa AND rec_n = 0 AND apu_n = 0 AND depositante = 0 AND antigüedad 8-30 d",
             obj="Primera recarga", momento="Envío único por jugador", salida="Primera recarga",
             kpi="Primera recarga en 14 días", vent="14 días", datos="Medios de pago vigentes y página de ayuda"),
        dict(c="REC06", t="Recuperación 31-60 días", tipo="Lote mensual",
             hall=f"{CF['tasa_rec06'][1]} de los inactivos de 31-60 días vuelve solo en 14 días; sin control no se sabe qué aporta el SMS.",
             seg="Inactivo 31-60 días", regla="ciclo_vida = inactivo_31_60", obj="Volver a apostar",
             momento="Mensual; variante según preferencia", salida="Nueva actividad",
             kpi="Retorno en 14 días", vent="14 días", datos=f"Teléfonos de la base histórica (+{n(h.inactivo)} jugadores)"),
    ]
    emb_aud, copies = D["emb_aud"], D["copies"]
    TK = D["ticket"]
    # Monto típico asociado a la acción objetivo de cada campaña (mediana observada).
    TICKET = {"ACT01": (TK.primera, "primera recarga mediana"), "ACT05": (TK.primera, "primera recarga mediana"),
              "ONB02": (TK.segunda, "segunda recarga mediana"), "XS03": (TK.apuesta1, "primera apuesta deportiva mediana"),
              "RET04": (TK.retorno, "recargado en 14 días por quien vuelve (mediana)"),
              "REC06": (TK.retorno, "recargado en 14 días por quien vuelve (mediana)")}
    ACCION = {"ACT01": "primeras recargas", "ACT05": "primeras recargas", "ONB02": "segundas recargas",
              "XS03": "primeras apuestas deportivas", "RET04": "jugadores que vuelven", "REC06": "jugadores que vuelven"}
    items, dets, camps_js = [], [], []
    total_envios = 0
    for i, c in enumerate(camp_def, 1):
        r = cam.loc[c["c"]]
        p0, base_txt = BASE[c["c"]]
        m = mde(p0, r.envio, r.control)
        total_envios += r.envio
        ea = emb_aud[emb_aud.campana == c["c"]].set_index("resultado").n
        excluidos = int(ea[[k for k in ea.index if k.startswith("excluido")]].sum())
        supr = int(ea.get("suprimido_por_prioridad", 0))
        tk, tk_lbl = TICKET[c["c"]]
        camps_js.append(dict(c=c["c"], t=c["t"], obj=c["obj"], accion=ACCION[c["c"]], envio=int(r.envio), control=int(r.control),
                             base=p0, mde=round(m, 2) if m else None, ticket=float(tk), vent=c["vent"]))
        cps = copies[copies.campana == c["c"]]
        bubbles, var_btns = "", ""
        for j, cp in enumerate(cps.itertuples()):
            cod, ln, sg, _ = analizar(cp.texto)
            txt = esc(cp.texto).replace("{link}", '<span class="lk">yjg.co/a1B2c</span>')
            vname = {"general": "General", "en_vivo": "En vivo", "prepartido": "Prepartido"}[cp.variante]
            bubbles += (f'<div class="bubble-var" data-v="{cp.variante}"{"" if j == 0 else " hidden"}>'
                        f'<div class="bubble">{txt}</div><div class="smeta">{cod} · {ln}/160 car. · {sg} segmento</div>'
                        f'<div class="smeta">Destino: {esc(cp.destino)}</div></div>')
            var_btns += f'<button type="button" class="btn" data-v="{cp.variante}" aria-pressed="{"true" if j == 0 else "false"}">{vname}</button>'
        vars_html = f'<div class="vars seg">{var_btns}</div>' if len(cps) > 1 else ""
        items.append(f'<button type="button" class="citem" data-c="{c["c"]}" aria-selected="false"><span class="code">{c["c"]}</span>'
                     f'<b>{i}. {c["t"]}</b><span>{n(r.envio)} SMS · objetivo: {c["obj"].lower()}</span></button>')
        dets.append(f"""<div class="cdet" data-c="{c['c']}" hidden>
  <div class="vhead"><div><h2 style="font-size:1.15rem">{i}. {c['t']}</h2><p>{c['hall']}</p></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><span class="chip warn">Pendiente de validación</span><span class="chip">{c['tipo']}</span></div></div>
  <div class="steps">
    <section class="step"><div class="sn">1</div><div class="sb"><h3>A quién</h3>
      <p><b>{n(r.seleccionados)} jugadores</b>: {c['seg'].lower()}. {n(r.envio)} reciben el SMS y {n(r.control)} quedan como control.</p>
      <p class="small muted">Regla: <code>{esc(c['regla'])}</code>. Fuera: cuenta no activa, teléfono inválido o compartido, señal de juego responsable, sin consentimiento ({excluidos} excluidos; {supr} ya están en una campaña de mayor prioridad).</p></div></section>
    <section class="step"><div class="sn">2</div><div class="sb"><h3>Qué recibe</h3>
      <div class="msg">{vars_html}<div class="phone"><div class="notch"></div><div class="from">YAjuego · ahora</div>{bubbles}</div></div></div></section>
    <section class="step"><div class="sn">3</div><div class="sb"><h3>Cuándo</h3>
      <p>{c['momento']}. Horario permitido: lun-vie 7-19 h y sáb 8-15 h. Máximo un SMS promocional por jugador por semana. Sale de la campaña al lograr el objetivo: {c['salida'].lower()}.</p></div></section>
    <section class="step res"><div class="sn">4</div><div class="sb"><h3>Resultado esperado <span class="sub">escenario <b class="esc-name">base</b></span></h3>
      <div class="rgrid">
        <div><span>Sin SMS</span><b class="r-sin">—</b><small>{base_txt}</small></div>
        <div><span>Con SMS</span><b class="r-con">—</b><small class="r-con-l"></small></div>
        <div class="hl"><span>Adicionales por el SMS</span><b class="r-add">—</b><small class="r-add-l"></small></div>
        <div><span>Monto asociado</span><b class="r-mon">—</b><small>{tk_lbl}: {cop(tk)}.</small></div>
      </div>
      <p class="r-medible small"></p></div></section>
    <section class="step"><div class="sn">5</div><div class="sb"><h3>Cómo sabremos si funcionó</h3>
      <p>Al cerrar la ventana de <b>{c['vent']}</b> se compara la tasa de <b>{c['kpi'].lower()}</b> del grupo envío contra el control. Con estos tamaños, el efecto mínimo que se puede confirmar en una ola es <b>±{n(m, 1)} p.p.</b>: pasar de {n(100 * p0, 1)} % a {n(100 * p0 + m, 1)} %. Efectos menores se confirman acumulando olas.</p></div></section>
  </div>
</div>""")

    # Vistas de activación (campañas, medición y plan) a partir de una plantilla sin llaves de f-string.
    ej = cam.loc["ACT01"]
    p0, p1 = BASE["ACT01"][0], BASE["ACT01"][0] * 1.25
    vistas_activacion = (VISTAS_ACTIVACION
        .replace("{ITEMS}", "".join(items)).replace("{DETS}", "".join(dets))
        .replace("{HIST}", n(h.atrasado + h.enfriando + h.inactivo)).replace("{SMS}", n(total_envios))
        .replace("{EJ_ENV}", n(ej.envio)).replace("{EJ_CTL}", n(ej.control))
        .replace("{EJ_ENV_C}", n(ej.envio * p1)).replace("{EJ_ENV_P}", f"{n(100 * p1, 1)} %")
        .replace("{EJ_CTL_C}", n(ej.control * p0)).replace("{EJ_CTL_P}", f"{n(100 * p0, 1)} %")
        .replace("{EJ_DIF}", f"+{n(100 * (p1 - p0), 1)} p.p.").replace("{EJ_ADD}", n(ej.envio * (p1 - p0)))
        .replace("{EJ_MDE}", n(mde(p0, ej.envio, ej.control), 1)).replace("{T_SIM}", fd(t_sim)))

    data_json = json.dumps({
        "cubo": D["cubo"].to_dict(orient="records"),
        "dicc": [] if "diccionario" in MODULOS_OCULTOS else D["dicc"][["tabla", "campo", "tipo", "definicion", "origen", "formula"]].to_dict(orient="records"),
        "ctrl": [] if "datos" in MODULOS_OCULTOS else D["ctrl"].fillna("").astype(str).to_dict(orient="records"),
        "camps": camps_js,
    }, ensure_ascii=False).replace("</", "<\\/")

    pend = int(cam.seleccionados.sum())

    # Pendientes de YAjuego: (qué, por qué importa, responsable, estado)
    hist_pot = int(h.atrasado + h.enfriando + h.inactivo)
    PEND = {
        "envio": [
            ("Lista de supresión: consentimiento y autoexclusión", "Ninguna audiencia se activa sin cruzarla.", "Cumplimiento", "crit"),
            ("Validación legal del texto y del horario", '"+18. Juega responsable.", opción de baja y horario de la Ley 2300 de 2023.', "Legal", "crit"),
            ("Enlaces de destino y acortador", "Cada SMS lleva a recargas, a la guía o a deportes; hoy usamos un enlace de ejemplo.", "CRM", "crit"),
            ("Proveedor y tarifa por SMS", "Sin tarifa no se calcula el costo por acción adicional.", "Mercadeo", "crit"),
        ],
        "alcance": [
            ("Teléfono y consentimiento de la base anterior a julio",
             f"{n(hist.j)} jugadores generan el {n(pct_apu_hist, 0)} % del monto apostado; {n(hist_pot)} están enfriándose o inactivos y hoy no se pueden contactar.",
             "CRM · Tecnología", "crit"),
            ("Carga diaria automática", "ACT01 funciona si el SMS sale a las 24 h del registro.", "Tecnología", "warn"),
        ],
        "precision": [
            ("Casino del 1 al 27 de octubre", "Quien solo jugó casino esos días puede aparecer como inactivo.", "Tecnología", "warn"),
            ("Días faltantes", ("Sin ningún archivo: " + sin_txt + ". " if sin_txt else "") + "Sin apuestas deportivas el 11 y el 13 de noviembre.", "Tecnología", "warn"),
            ("Diccionario de códigos", "Estado de cuenta (hoy solo 1 = activa), KYC, apuestas Live = 2 y zona horaria.", "Tecnología", "neu"),
            ("Medios de pago vigentes", "Los SMS mencionan YAJUEGO PAGOS, PSE y Bre-B.", "Mercadeo", "neu"),
        ],
    }
    n_pend = sum(len(v) for v in PEND.values())
    EST = {"crit": ("crit", "Pendiente · bloquea"), "warn": ("warn", "Pendiente"), "neu": ("neu", "Por confirmar")}
    TIT = {"envio": "Bloquean el envío", "alcance": "Amplían el alcance", "precision": "Afinan los segmentos"}
    pend_html = ""
    for g, items in PEND.items():
        filas_p = "".join(f'<tr><td><b>{esc(q)}</b></td><td>{esc(pq)}</td><td class="small muted">{esc(r)}</td>'
                          f'<td><span class="pill {EST[e][0]}">{EST[e][1]}</span></td></tr>' for q, pq, r, e in items)
        pend_html += (f'<section class="panel"><div class="ph"><h2>{TIT[g]}</h2><span class="sub">{len(items)}</span></div>'
                      f'<div class="pb flush"><div class="tw"><table class="wide"><thead><tr><th>Pendiente</th><th>Por qué importa</th>'
                      f'<th>Responsable</th><th>Estado</th></tr></thead><tbody>{filas_p}</tbody></table></div></div></section>\n  ')

    # ---------- predicción (regresión logística) ----------
    pct = lambda x, d=0: f"{n(100 * x, d)} %"  # noqa: E731

    def dias(x):
        x = int(round(x))
        return f"{x} día" if x == 1 else f"{x} días"

    # Cómo leer cada factor: título, frase con probabilidades concretas y acción. {lo}/{hi}: valores; {plo}/{phi}: probabilidades.
    # Cada factor: título, comparación corta (probabilidad con valor bajo · alto) y acción en una línea.
    FACTORES_TXT = {
        "abandono": {
            "dias_activos_30": ("Frecuencia en el último mes", "Jugó {lo_d} de 30: {plo} · jugó {hi_d}: {phi}",
                                "Retener primero a los de baja frecuencia (RET04)."),
            "dias_sin_actividad": ("Días sin jugar", "{lo_d} sin jugar: {plo} · {hi_d}: {phi}",
                                   "Enviar RET04 entre el día 7 y el 14 sin jugar."),
            "verificado": ("Celular verificado", "Sin verificar: {plo} · verificado: {phi}",
                           "Pedir verificar el celular al registrarse."),
            "antiguedad_dias": ("Tiempo como jugador", "{lo_d}: {plo} · {hi_d}: {phi}",
                                "Reforzar los dos primeros meses (ONB02)."),
            "registrado_desde_julio": ("Nuevo o histórico", "Base histórica: {plo} · registrado desde julio: {phi}",
                                       "Acompañar las primeras semanas del jugador nuevo."),
        },
        "activacion": {
            "aposto_sin_recargar": ("Ya apostó sin recargar", "No ha apostado: {plo} · ya apostó: {phi}",
                                    "Contactarlos primero en ACT01."),
            "verificado": ("Celular verificado", "Sin verificar: {plo} · verificado: {phi}",
                           "Recordar la verificación al invitar a recargar."),
            "dias_desde_registro": ("Días desde el registro", "{lo_d}: {plo} · {hi_d}: {phi}",
                                    "Enviar ACT01 en las primeras 24-72 h."),
            "telefono_valido": ("Teléfono válido", "Inválido: {plo} · válido: {phi}",
                                "Validar el celular en el formulario de registro."),
        },
    }
    FACTORES_TXT.update({
        "habito": {
            "dias_sin_apostar": ("Días desde su última apuesta", "{lo_d}: {plo} · {hi_d}: {phi}", "Contactar en la misma semana de su última apuesta."),
            "dias_apuesta_30": ("Días con apuesta en el último mes", "{lo_d} de 30: {plo} · {hi_d}: {phi}", "Empezar por quien ya apuesta 2 a 4 días al mes."),
            "registrado_desde_julio": ("Nuevo o histórico", "Base histórica: {plo} · registrado desde julio: {phi}", ""),
            "tendencia_apuesta": ("Cambio frente al mes anterior", "{lo_s} días con apuesta: {plo} · {hi_s} días: {phi}", ""),
        },
        "cruzada_deportes": {
            "log_recargas_30": ("Recargas en el último mes", "{lo_n}: {plo} · {hi_n}: {phi}", "Empezar por los ocasionales: quien recarga mucho ya tiene su juego en casino."),
            "verificado": ("Celular verificado", "Sin verificar: {plo} · verificado: {phi}", ""),
            "registrado_desde_julio": ("Nuevo o histórico", "Base histórica: {plo} · registrado desde julio: {phi}", ""),
        },
        "modalidad": {
            "solo_prepartido": ("Modalidad actual", "Solo en vivo → prueba prepartido: {plo} · solo prepartido → prueba en vivo: {phi}",
                                "Es más fácil llevar a prepartido al que apuesta en vivo que al revés."),
            "dias_sin_apostar": ("Días desde su última apuesta", "{lo_d}: {plo} · {hi_d}: {phi}", "Proponer la otra modalidad mientras está activo."),
            "registrado_desde_julio": ("Nuevo o histórico", "Base histórica: {plo} · registrado desde julio: {phi}", ""),
        },
    })
    PRED_TXT = {
        "abandono": dict(titulo="Abandono en 30 días", pob="jugadores activos en los últimos 30 días",
                         evento="dejarían de jugar", corto="abandonos", banda="Riesgo alto", prob="Probabilidad de irse",
                         auc_tip="Entre un jugador que se fue y uno que siguió, el modelo le da más riesgo al que se fue {} de cada 100 veces.",
                         pasos=['RET04: en el <a href="#audiencias">Constructor</a>, filtra «Riesgo de abandono alto» + «Enfriándose».',
                                "Activos con riesgo alto: solo mensajes de servicio.",
                                'Riesgo alto sin teléfono: pedir sus datos a YAjuego (<a href="#ajustes">Pendientes</a>).'],
                         accion={"3_activo": "Mensajes de servicio", "4_enfriandose": "RET04",
                                 "2_nuevo_en_activacion": "ONB02", "5_inactivo_31_60": "REC06"}),
        "activacion": dict(titulo="Primera recarga en 14 días", pob="registrados sin recarga en los últimos 30 días",
                           evento="harían su primera recarga", corto="primeras recargas", banda="Probabilidad alta", prob="Probabilidad de recargar",
                           auc_tip="Entre un registrado que recargó y uno que no, el modelo le da más probabilidad al que recargó {} de cada 100 veces.",
                           pasos=['ACT01 y ACT05: en el <a href="#audiencias">Constructor</a>, empieza por «Prob. de activarse alta».',
                                  "Probabilidad baja y más de 21 días: enviar solo como prueba con control.",
                                  "Automatizar la carga diaria para enviar ACT01 a las 24-72 h."],
                           accion={"1_nuevo_sin_actividad": "ACT01 (0-7 días) · ACT05 (8-30 días)"}),
        "habito": dict(titulo="Volverse habitual en 30 días", pob="apostadores ocasionales (1 a 4 días al mes)",
                       evento="apostarían 5 días o más", corto="nuevos habituales", banda="Probabilidad alta", prob="Probabilidad de volverse habitual",
                       auc_tip="Entre un ocasional que se volvió habitual y uno que no, el modelo le da más probabilidad al primero {} de cada 100 veces.",
                       pasos=['En el <a href="#audiencias">Constructor</a>, filtra «Oportunidad: volverse habitual».',
                              "Mensaje: la agenda de partidos de su modalidad preferida, sin bonos.",
                              "Un SMS por semana como máximo."],
                       accion={"3_activo": "Agenda deportiva semanal", "4_enfriandose": "RET04 con agenda"}),
        "cruzada_deportes": dict(titulo="Primera apuesta deportiva en 30 días", pob="jugadores que recargan y no apuestan en deportes",
                                 evento="harían su primera apuesta deportiva", corto="primeras apuestas deportivas", banda="Probabilidad alta",
                                 prob="Probabilidad de apostar en deportes",
                                 auc_tip="Entre un jugador que probó deportes y uno que no, el modelo le da más probabilidad al primero {} de cada 100 veces.",
                                 pasos=['XS03: en el <a href="#audiencias">Constructor</a>, empieza por «Oportunidad: deportes».',
                                        "Mensaje: cómo funciona una apuesta simple y la agenda del fin de semana.",
                                        "No interrumpir a quien juega casino a diario."],
                                 accion={"3_activo": "XS03", "2_nuevo_en_activacion": "XS03", "4_enfriandose": "XS03 con agenda"}),
        "modalidad": dict(titulo="Probar la otra modalidad en 30 días", pob="apostadores que solo usan prepartido o solo en vivo",
                          evento="probarían la otra modalidad", corto="cambios de modalidad", banda="Probabilidad alta",
                          prob="Probabilidad de probar la otra modalidad",
                          auc_tip="Entre un apostador que probó la otra modalidad y uno que no, el modelo le da más probabilidad al primero {} de cada 100 veces.",
                          pasos=['En el <a href="#audiencias">Constructor</a>, filtra «Oportunidad: otra modalidad».',
                                 "Solo prepartido: partidos en vivo del día. Solo en vivo: la agenda con anticipación.",
                                 "Es la misma variante de mensaje que ya usan RET04 y REC06."],
                          accion={"3_activo": "Variante por modalidad", "4_enfriandose": "RET04 con variante"}),
    }

    def frase(f, k):
        t = FACTORES_TXT[k].get(f["variable"])
        vals = dict(lo_d=dias(f["desde"]), hi_d=dias(f["hasta"]), plo=pct(f["p_desde"], 0 if f["p_desde"] >= 0.1 else 1),
                    phi=pct(f["p_hasta"], 0 if f["p_hasta"] >= 0.1 else 1), lo_n=n(f["desde"]), hi_n=n(f["hasta"]),
                    lo_p=pct(f["desde"], 0), hi_p=pct(f["hasta"], 0), lo_m=cop(round(f["desde"], -3)), hi_m=cop(round(f["hasta"], -3)),
                    lo_s=f"{'+' if f['desde'] > 0 else ''}{n(f['desde'])}", hi_s=f"{'+' if f['hasta'] > 0 else ''}{n(f['hasta'])}")
        if t:
            return t[0], t[1].format(**vals), t[2]
        u = f["unidad"]
        lo, hi = {"días": ("lo_d", "hi_d"), "%": ("lo_p", "hi_p"), "$": ("lo_m", "hi_m")}.get(u, ("lo_n", "hi_n"))
        if u == "sí/no":
            return f["nombre"].capitalize(), f"No: {vals['plo']} · sí: {vals['phi']}", ""
        sufijo = "" if u in ("días", "%", "$") else f" {u}"
        return f["nombre"].capitalize(), f"{vals[lo]}{sufijo}: {vals['plo']} · {vals[hi]}{sufijo}: {vals['phi']}", ""

    bloques = {}
    for m in D["pred"]:
        k = m["modelo"]
        pred_html = ""
        tx = PRED_TXT[k]
        ps = D["pred_seg"][D["pred_seg"].modelo == k]
        tot, esp = int(ps.n.sum()), float(ps.esperado.sum())
        alta = ps[ps.banda == "alta"]
        n_alta, p_alta, c_alta = int(alta.n.sum()), float(alta.esperado.sum() / max(alta.n.sum(), 1)), int(alta.contactables.sum())
        seg = ps.groupby("ciclo_vida").agg(n=("n", "sum"), esp=("esperado", "sum")).reset_index()
        alta_seg = alta.groupby("ciclo_vida").agg(na=("n", "sum"), ca=("contactables", "sum")).reset_index()
        seg = seg.merge(alta_seg, on="ciclo_vida", how="left").fillna(0).sort_values("n", ascending=False)
        seg = seg[seg.n >= 50]
        filas = [dict(s=f"<strong>{NOMBRES_CV.get(r.ciclo_vida, r.ciclo_vida)}</strong>", n=n(r.n), e=n(r.esp), p=pct(r.esp / r.n, 1),
                      a=n(r.na), c=n(r.ca), q=tx["accion"].get(r.ciclo_vida, "—")) for r in seg.itertuples()]
        t_seg_p = table(pd.DataFrame(filas), [("s", "Segmento"), ("n", "Jugadores"), ("e", "Se irían" if k == "abandono" else "Lo harían"),
                                              ("p", "Prob. promedio"), ("a", "En banda alta"), ("c", "Contactables"), ("q", "Qué hacer")],
                        num=("n", "e", "p", "a", "c"))
        cal = pd.DataFrame(m["calibracion"])
        f_cal = bars_v([f"{i + 1}" for i in cal.index], [("Lo que el modelo predijo", list(100 * cal.pred), "--s1"),
                                                         ("Lo que realmente pasó", list(100 * cal.real), "--s2")],
                       fmt=lambda v: f"{n(v, 1)} %" if v < 10 else f"{n(v, 0)} %", h=240, labels=False,
                       sub=["menor prob." if i == 0 else ("mayor prob." if i == len(cal) - 1 else "") for i in cal.index])
        sel = [f for f in m["factores"] if abs(f["diferencia"]) >= (0.02 if k == "abandono" else 0.005) and abs(f["diferencia"]) >= 0.15 * max(abs(x["diferencia"]) for x in m["factores"])][:5]
        otros = [f["nombre"] for f in m["factores"] if f not in sel]
        fac = ""
        for f in sel:
            tit, txt, acc = frase(f, k)
            sube = f["p_hasta"] > f["p_desde"]
            malo = sube == (k == "abandono")
            fac += (f'<div class="li"><span class="ic {"crit" if malo else "ok"}">{"↑" if sube else "↓"}</span><div><b>{esc(tit)}</b>'
                    f'<span class="mono" style="display:block">{txt}</span>' + (f'<span style="display:block;color:var(--accent)">→ {acc}</span>' if acc else '')
                    + '</div><span></span></div>')
        pasos = "".join(f"<li>{x}</li>" for x in tx["pasos"])
        azar = "al azar se llegaría al 20 %"
        pred_html += f"""
  <section class="panel"><div class="ph"><h2>{tx['titulo']}</h2><span class="sub">{n(tot)} {tx['pob']}</span></div><div class="pb">
    <div class="g g4">
      {tile('Pronóstico', n(esp), f"{tx['evento']} · {n(100 * esp / tot, 0)} % de {n(tot)}", acc=True, tip=f"Suma de las probabilidades de los {n(tot)} {tx['pob']}.")}
      {tile(tx['banda'], n(n_alta), f"{n(c_alta)} contactables · prob. media {pct(p_alta, 0 if p_alta >= 0.1 else 1)}", tip="El 20 % con mayor probabilidad.")}
      {tile('Cobertura del 20 % alto', f"{n(100 * m['captura_top20'], 0)}<small> %</small>", f"de los {tx['corto']} reales (al azar: 20 %)", tip="Medido en jugadores que el modelo no usó para aprender.")}
      {tile('Confiabilidad', n(m['auc'], 2), ("Buena" if m['auc'] >= 0.75 else "Media: útil para priorizar" if m['auc'] >= 0.65 else "Baja") + " · 0,5 es azar", tip=tx['auc_tip'].format(n(100 * m['auc'], 0)))}
    </div>
    <div class="g g2">
      <div><h3 style="margin-bottom:8px">{tx['prob']} según…{info("Jugadores que solo se diferencian en ese factor. Es asociación, no causa: sirve para elegir a quién contactar y cuándo.")}</h3>
        <div class="list">{fac}</div>
        {f'<p class="small muted" style="margin-top:8px">Pesan poco: {", ".join(otros)}.</p>' if otros else ''}</div>
      <div><h3 style="margin-bottom:8px">Predicho vs. real{info(f"Prueba con {n(m['n_validacion'])} jugadores al {pd.Timestamp(m['t_validacion']):%d-%m} que el modelo no vio, en 10 grupos de menor a mayor probabilidad. Si las barras se parecen, el modelo acierta.")}</h3>
        {f_cal}</div>
    </div>
    <h3>Por segmento</h3>
    {t_seg_p}
    <div class="note"><b>Qué hacer</b><ul style="margin:2px 0 0;padding-left:18px;display:grid;gap:2px">{pasos}</ul></div>
  </div></section>"""
        bloques[k] = pred_html
    _op = D["pred_seg"][D["pred_seg"].modelo.isin(["habito", "cruzada_deportes", "modalidad"]) & (D["pred_seg"].banda == "alta")]
    op_alta, op_cont = int(_op.n.sum()), int(_op.contactables.sum())
    # Afinidad con casino (descriptivo mientras no haya historia para un modelo)
    af = D["afinidad"]
    afd = pd.DataFrame(af["grupos"])
    filas_af = []
    for dim, g in afd.groupby("dimension", sort=False):
        top_ = g.sort_values("pct_casino", ascending=False)
        filas_af.append(dict(d=f"<strong>{dim}</strong>", alto=f"{top_.iloc[0].grupo} · {pct(top_.iloc[0].pct_casino)}",
                             bajo=f"{top_.iloc[-1].grupo} · {pct(top_.iloc[-1].pct_casino)}"))
    t_af = table(pd.DataFrame(filas_af), [("d", "Según"), ("alto", "Más juega casino"), ("bajo", "Menos juega casino")])
    casino_html = f"""
  <section class="panel"><div class="ph"><h2>Venta cruzada a casino</h2><span class="pill neu">Modelo en preparación</span></div><div class="pb">
    <div class="g g3">
      {tile('Apostadores de deportes', n(af['apostadores']), f"desde el {fd(cas_d0)}")}
      {tile('Ya juegan casino', f"{n(100 * af['pct_casino'], 0)}<small> %</small>", "de esos apostadores", acc=True)}
      {tile('Modelo disponible', "mediados de dic.", "con 6 a 8 semanas de casino", tip="Para predecir con rigor hace falta ver varias semanas de casino antes y después de cada corte.")}
    </div>
    <h3>Quién se parece a los que ya juegan casino</h3>
    {t_af}
    <div class="note"><b>Qué hacer</b><span>Mientras llega el modelo, probar casino con un piloto pequeño en los perfiles con más afinidad, con grupo de control.</span></div>
  </div></section>"""
    pred_html = f"""<section class="view" id="v-prediccion" data-title="Predicción · Abandono y activación">
  <div class="vhead"><div><h1>Abandono y activación</h1><p>Quién se va a ir y quién está por hacer su primera recarga.</p></div>
    <div class="seg"><a class="btn" href="#prediccion" aria-current="page" style="background:var(--fg);color:var(--panel)">Abandono y activación · 2</a><a class="btn" href="#crecimiento">Crecimiento · 3</a></div></div>
  {bloques['abandono']}{bloques['activacion']}
  <details class="how"><summary>¿Cómo funcionan los modelos?</summary>Regresión logística reentrenada con cada carga. Aprende de lo que hicieron jugadores parecidos en semanas anteriores y se prueba en la semana más reciente, que no vio. Solo usa datos conocidos en cada fecha; casino entra cuando tenga más historia (existe desde el {fd(cas_d0)}). Predice quién; el efecto del SMS lo mide el grupo de control.</details>
</section>

<section class="view" id="v-crecimiento" data-title="Predicción · Crecimiento">
  <div class="vhead"><div><h1>Crecimiento</h1><p>Quién está listo para jugar más seguido o probar otro producto.</p></div>
    <div class="seg"><a class="btn" href="#prediccion">Abandono y activación · 2</a><a class="btn" href="#crecimiento" aria-current="page" style="background:var(--fg);color:var(--panel)">Crecimiento · 3</a></div></div>
  <div class="g g2">
    <div class="note"><b>Dónde está el crecimiento</b><span>De {n(op_alta)} jugadores con probabilidad alta en los tres modelos, solo {n(op_cont)} tienen teléfono. El resto es base anterior a julio: <a href="#ajustes">pedir sus datos</a> multiplica este módulo.</span></div>
    <div class="note"><b>Crecimiento responsable</b><span>Más frecuencia, no montos más altos. Fuera quien tiene señales de juego responsable y el 1 % de mayor intensidad; sin bonos y máximo un SMS por semana.</span></div>
  </div>
  {bloques['habito']}{bloques['cruzada_deportes']}{bloques['modalidad']}{casino_html}
</section>
"""
    nav = [("Operación", [("inicio", "home", "Inicio", ""), ("datos", "db", "Fuentes de datos", str(int((D['manifiesto'].estado == 'cargado').sum()))),
                          ("modelo", "model", "Modelo", ""), ("diccionario", "book", "Diccionario", str(len(D['dicc'])))]),
           ("Clientes", [("jugadores", "users", "Jugadores", n(D['universo_base'])), ("insights", "spark", "Insights", "7"), ("segmentos", "users", "Segmentos", "7"), ("audiencias", "filter", "Constructor", "")]),
           ("Predicción", [("prediccion", "gauge", "Abandono y activación", "2"), ("crecimiento", "spark", "Crecimiento", "3")]),
           ("Seguimiento", [("octubre", "spark", "Tendencias y casino", "")]),
           ("Activación", [("campanas", "send", "Campañas SMS", "6"), ("medicion", "gauge", "Medición", ""), ("plan", "map", "Plan", "")]),
           ("Cuenta", [("ajustes", "cog", "Pendientes", str(n_pend))])]
    nav_html = "".join(f'<div class="grp">{g}</div>' + "".join(
        f'<a href="#{k}">{icon(ic)}<span>{lbl}</span>{f"<span class=badge>{b}</span>" if b else ""}</a>' for k, ic, lbl, b in its if k not in MODULOS_OCULTOS)
        for g, its in nav)

    body = f"""<title>Vincero · YAjuego</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="icon" href="data:image/png;base64,{mark_b}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
<div class="app">
<aside class="side">
  <div class="brand"><img src="data:image/png;base64,{logo_w}" alt="Vincero"></div>
  <div class="ws"><small>Espacio de trabajo</small><b>YAjuego · CRM SMS</b><span>Corte {corte:%d-%m-%Y} · reglas v1.0</span></div>
  <nav class="nav" aria-label="Módulos">{nav_html}</nav>
  <div class="side-foot">
    <div class="row"><span class="led{'' if not fallas else ' w'}"></span>{'Datos verificados' if not fallas else f'{fallas} diferencias en los datos'}</div>
    <div class="row"><span class="led w"></span>Audiencias pendientes de validación</div>
    <div class="row mono">Generado {pd.Timestamp.today():%d-%m-%Y}</div>
  </div>
</aside>
<div class="main">
  <header class="top">
    <div class="crumb">YAjuego <span>/</span> <b id="crumb-view">Inicio</b></div>
    <div class="status">
      <span class="chip ok">Datos hasta {ultimo:%d-%m-%Y}</span>
      <span class="chip warn">Segmentos y campañas al {corte:%d-%m-%Y}</span>
      <span class="chip {'ok' if not fallas else 'crit'}" title="{n_ctrl} controles de conciliación entre origen, base y audiencias">{'Datos verificados' if not fallas else f'{fallas} diferencias en los datos'}</span>
      <span class="chip warn">Consentimiento pendiente</span>
      <span class="chip warn">Casino desde el {fd(cas_d0)}</span>
    </div>
  </header>
  <main class="content">

<section class="view" id="v-inicio" data-title="Inicio">
  <div class="vhead"><div><h1>Inicio</h1><p>Tu base al {corte:%d-%m-%Y}. Todo se recalcula con cada carga de datos.</p></div><span class="chip acc">Última actualización de datos: {ultimo:%d-%m-%Y}</span></div>
  <section class="panel"><div class="ph"><h2>Actividad · {periodo_txt}</h2><a class="btn" href="#octubre">Ver tendencias</a></div><div class="pb">
    <div class="g g4">
      {tile('Recargas', mm(rec.m), f"{n(rec.n)} recargas · {n(rec.j)} jugadores")}
      {tile('Apuestas deportivas', mm(apu.m), f"{n(apu.n)} apuestas · {n(apu.j)} jugadores")}
      {tile('Casino', mm(cas.ap), f"{n(cas.jug)} jugadores · desde el {fd(cas_d0)}", acc=True, tip=f"Monto apostado en {n(cas.rondas)} rondas. No hay datos de casino antes del {fd(cas_d0)}.")}
      {tile('Retiros', mm(retd.m), f"{n(retd.n)} retiros · {n(retd.j)} jugadores", tip="Monto pagado a los jugadores, neto de comisiones.")}
    </div>
    <p class="small muted">Faltan datos: {', '.join(x for x in [sin_txt and 'todo el ' + sin_txt, dep_txt and 'deportes del ' + dep_txt, 'casino antes del ' + fd(cas_d0)] if x)}.{info(f"Además, {n_rec} combinaciones de día y fuente llegaron incompletas. Los promedios por día solo usan días completos.")} <a href="#ajustes">Ver pendientes</a></p>
  </div></section>
  <div class="g g4">
    {tile('Jugadores', n(D['universo']), f"{n(reg_tot.j)} con teléfono", tip="Todos los que aparecen en algún archivo desde el 1-jul. Solo los registrados desde julio traen teléfono.")}
    {tile('Monto sin contacto', f"{n(pct_apu_hist, 0)}<small> %</small>", f'del apostado viene de jugadores sin teléfono · <a href="#ajustes">Pedir datos</a>', acc=True, tip=f"{n(hist.j)} jugadores registrados antes de julio generan este monto y no tenemos cómo contactarlos.")}
    {tile('Registrados que recargan', f"{n(conv_tot, 1)}<small> %</small>", f"{n(pct_24h, 0)} % lo hace en las primeras 24 h", tip="Por eso el SMS de activación (ACT01) debe salir el mismo día del registro.")}
    {tile('En campañas', n(pend), f'{n(total_envios)} SMS · {n(pend - total_envios)} control · <a href="#campanas">Ver</a>', tip="El grupo de control no recibe mensaje: sirve para medir cuánto aporta el SMS.")}
  </div>
  <div class="g g-73">
    <section class="panel"><div class="ph"><h2>Actividad diaria</h2><span class="sub">{periodo_txt} · días completos</span></div><div class="pb">{f_dia}</div></section>
    <section class="panel"><div class="ph"><h2>Alertas</h2></div><div class="pb flush"><div class="list">
      <div class="li"><span class="ic crit">!</span><div><b>Base histórica sin teléfono</b><span>{n(hist.j)} jugadores, {n(pct_apu_hist, 0)} % del monto apostado.</span></div><a class="btn" href="#ajustes">Ver</a></div>
      <div class="li"><span class="ic crit">!</span><div><b>Consentimiento y autoexclusión</b><span>Falta la lista de supresión para poder enviar.</span></div><a class="btn" href="#ajustes">Ver</a></div>
      <div class="li"><span class="ic ok">✓</span><div><b>Audiencias recalculadas al {corte:%d-%m-%Y}</b><span>Con toda la base, {periodo_txt}.</span></div><a class="btn" href="#plan">Ver</a></div>
      <div class="li"><span class="ic crit">!</span><div><b>Huecos en los datos</b><span>Casino solo desde el {fd(cas_d0)}{('; sin datos el ' + sin_txt) if sin_txt else ''}.</span></div><a class="btn" href="#octubre">Ver</a></div>
      <div class="li"><span class="ic acc">i</span><div><b>Su producto es casino</b><span>{n(pct_sr_cas, 0)} % de quienes no apuestan en deportes juega casino.</span></div><a class="btn" href="#octubre">Ver</a></div>
      {'' if not fallas else f'<div class="li"><span class="ic crit">!</span><div><b>Diferencias en los datos</b><span>{fallas} de {n_ctrl} controles no cuadran: no enviar hasta revisarlos.</span></div><span></span></div>'}
    </div></div></section>
  </div>
  <div class="note"><b>Lectura de Vincero</b><span>El mayor potencial está en {n(h.atrasado + h.enfriando + h.inactivo)} jugadores de la base anterior a julio que se están alejando. Con su teléfono y consentimiento, la retención pasa de cientos a miles de jugadores.</span></div>
</section>

<section class="view" id="v-datos" data-title="Fuentes de datos">
  <div class="vhead"><div><h1>Fuentes de datos</h1><p>Cada archivo se identifica por su huella SHA-256, se clasifica por sus columnas y su periodo se lee del contenido, no del nombre.</p></div></div>
  <div class="g g4">
    {tile('Archivos recibidos', n(D['n_archivos']), f"{n(D['n_cargados'])} cargados · 1 copia idéntica omitida")}
    {tile('Filas cargadas', n(rec.n + D['lin'] + retd.n + D['reg']), 'Registros, recargas, líneas de apuesta y retiros')}
    {tile('Controles', f"{n_ctrl}", f"{fallas} fallas", acc=True)}
    {tile('Casino', n(cas.rondas), f"Rondas desde el {fd(cas_d0)}")}
  </div>
  <section class="panel"><div class="ph"><h2>Historial de cargas</h2><span class="sub">meta.manifiesto</span></div><div class="pb flush"><div class="tw">{t_man.replace('<div class="tw">', '').replace('</table></div>', '</table>')}</div></div></section>
  <section class="panel"><div class="ph"><h2>Controles de conciliación</h2>
    <div class="seg" id="ctrl-tabs"><button type="button" data-f="todos" aria-pressed="true">Todos</button><button type="button" data-f="OK" aria-pressed="false">OK</button><button type="button" data-f="FALLA" aria-pressed="false">Fallas</button><button type="button" data-f="INFO" aria-pressed="false">Info</button></div></div>
    <div class="pb flush"><div class="tw"><table class="wide"><thead><tr><th>Control</th><th class="num">Esperado</th><th class="num">Obtenido</th><th>Estado</th><th>Nota</th></tr></thead><tbody id="ctrl-body"></tbody></table></div></div></section>
  <div class="g g4">
    <section class="panel"><div class="ph"><h2>Uso directo</h2><span class="pill ok">OK</span></div><div class="pb small"><ul style="margin:0;padding-left:18px;display:grid;gap:4px">
      <li>ID de jugador común a las cuatro fuentes</li><li>IDs de transacción únicos</li><li>0 fechas o montos no convertibles</li><li>Montos en COP ({CF["cop_eur"]} COP/EUR implícito)</li><li>0 registros de prueba; edad mínima 18</li></ul></div></section>
    <section class="panel"><div class="ph"><h2>Limpieza aplicada</h2><span class="pill warn">Resuelto</span></div><div class="pb small"><ul style="margin:0;padding-left:18px;display:grid;gap:4px">
      <li>Números guardados como texto</li><li><code>SubBet ID</code> sin precisión: no se usa como llave</li><li>Apuestas SYSTEM: {n(D['lin'] - apu.n)} líneas extra</li>
      <li>{n(tel.get('valido_con_prefijo_57', 0))} teléfonos normalizados; {n(tel.get('invalido_o_incompleto', 0))} inválidos; {n(D['tel_comp'])} compartidos</li></ul></div></section>
    <section class="panel"><div class="ph"><h2>Validar con YAjuego</h2><span class="pill neu">Abierto</span></div><div class="pb small"><ul style="margin:0;padding-left:18px;display:grid;gap:4px">
      <li>Códigos de estado de cuenta (solo 1 = activa)</li><li>KYC, fuente de registro, red 601/602</li><li><code>Live = 2</code> como combinada mixta</li><li>Zona horaria (perfil indica hora Colombia)</li></ul></div></section>
    <section class="panel"><div class="ph"><h2>No disponible</h2><span class="pill crit">Falta</span></div><div class="pb small"><ul style="margin:0;padding-left:18px;display:grid;gap:4px">
      <li>Casino antes del {fd(cas_d0)}{(' y todo el ' + sin_txt) if sin_txt else ''}</li><li>Contacto de la base anterior a julio</li><li>Deporte, liga, evento, mercado</li><li>GGR/NGR y pérdida por jugador</li><li>Operaciones fallidas o anuladas</li><li>Consentimiento y autoexclusión</li></ul></div></section>
  </div>
</section>

<section class="view" id="v-modelo" data-title="Modelo">
  <div class="vhead"><div><h1>Modelo de datos</h1><p>Base DuckDB en un archivo, alimentada por scripts versionados. Cada fuente se agrega por separado y se une 1 a 1 por jugador, para que ningún cruce multiplique montos.</p></div></div>
  <section class="panel"><div class="ph"><h2>Flujo del pipeline</h2><span class="sub">python pipeline/run.py · ~1 minuto · idempotente</span></div><div class="pb flush"><div class="flow">
    <div class="st"><code>data/raw</code><b>Originales</b><span class="n">{n(D['n_archivos'])}</span><span>Excel intactos con hash</span></div>
    <div class="st"><code>stg.*</code><b>Staging</b><span class="n">{n(rec.n + D['lin'] + retd.n + D['reg'])}</span><span>Texto tal cual + archivo y fila</span></div>
    <div class="st"><code>core.*</code><b>Datos limpios</b><span class="n">6 tablas</span><span>Tipos, llaves únicas, teléfonos</span></div>
    <div class="st"><code>mart.jugador_resumen</code><b>Perfil por jugador</b><span class="n">{n(D['universo'])}</span><span>100+ indicadores al corte</span></div>
    <div class="st"><code>mart.segmento_jugador</code><b>Segmentos</b><span class="n">7 + 11</span><span>Con versión de reglas</span></div>
    <div class="st"><code>mart.audiencia_sms</code><b>Audiencias</b><span class="n">{n(pend)}</span><span>Envío y control</span></div>
  </div></div></section>
  <div class="g g2">
    <section class="panel"><div class="ph"><h2>Tablas</h2></div><div class="pb flush"><div class="tw"><table><thead><tr><th>Tabla</th><th>Unidad</th><th class="num">Filas</th><th>Llave</th></tr></thead><tbody>
      <tr><td><code>core.jugador</code></td><td>Jugador visto en cualquier fuente</td><td class="num">{n(D['universo'])}</td><td>player_id</td></tr>
      <tr><td><code>core.registro</code></td><td>Registrado desde julio (sin nombre, dirección, documento ni IP)</td><td class="num">{n(D['reg'])}</td><td>player_id</td></tr>
      <tr><td><code>core.recarga</code></td><td>Recarga acreditada</td><td class="num">{n(rec.n)}</td><td>recarga_id</td></tr>
      <tr><td><code>core.apuesta</code></td><td>Apuesta (ticket)</td><td class="num">{n(apu.n)}</td><td>bet_id</td></tr>
      <tr><td><code>core.apuesta_linea</code></td><td>Línea de apuesta</td><td class="num">{n(D['lin'])}</td><td>bet_id + tipo</td></tr>
      <tr><td><code>core.retiro</code></td><td>Retiro procesado</td><td class="num">{n(retd.n)}</td><td>retiro_id</td></tr>
    </tbody></table></div></div></section>
    <section class="panel"><div class="ph"><h2>Reglas de consolidación</h2></div><div class="pb flush"><div class="list">
      <div class="li"><span class="ic acc">ID</span><div><b>Identidad</b><span>ID/Client ID como texto. Nunca se unen personas por nombre, correo o teléfono.</span></div><span></span></div>
      <div class="li"><span class="ic acc">57</span><div><b>Teléfonos</b><span>10 dígitos iniciando en 3, o 12 con prefijo 57. No se completan dígitos.</span></div><span></span></div>
      <div class="li"><span class="ic acc">↺</span><div><b>Re-ejecución</b><span>Un archivo ya cargado se reconoce por su hash y se omite. Si una transacción aparece en dos cargas, gana la más reciente.</span></div><span></span></div>
      <div class="li"><span class="ic acc">Δ</span><div><b>Correcciones de un mes</b><span>Un archivo que contiene el periodo de otro y comparte ≥ 50 % de sus IDs lo reemplaza sin borrar nada.</span></div><span></span></div>
      <div class="li"><span class="ic acc">0</span><div><b>Cero vs desconocido</b><span>0 = sin actividad observada; vacío = dato desconocido; "observada" ≠ "histórica".</span></div><span></span></div>
    </div></div></section>
  </div>
</section>

<section class="view" id="v-diccionario" data-title="Diccionario">
  <div class="vhead"><div><h1>Diccionario de datos</h1><p>Campos de las tablas limpias y de consumo, con tipo real, origen y fórmula.</p></div>
    <label class="search"><span class="muted small">Buscar</span><input id="dicc-q" type="search" placeholder="campo, definición u origen"></label></div>
  <section class="panel"><div class="ph"><div class="seg" id="dicc-tabs">
      <button type="button" data-t="todas" aria-pressed="true">Todas</button><button type="button" data-t="core" aria-pressed="false">core</button><button type="button" data-t="mart" aria-pressed="false">mart</button></div>
      <span class="sub" id="dicc-n"></span></div>
    <div class="pb flush"><div class="tw" style="max-height:640px"><table class="wide"><thead><tr><th>Tabla</th><th>Campo</th><th>Tipo</th><th>Definición</th><th>Origen</th><th>Fórmula / regla</th></tr></thead><tbody id="dicc-body"></tbody></table></div></div></section>
</section>

<section class="view" id="v-jugadores" data-title="Jugadores">
  <div class="vhead"><div><h1>Jugadores</h1><p>Quién juega y qué hace, desde el 1-jul.</p></div></div>
  <div class="g g4">
    {tile('Jugadores', n(tot_j), 'Con actividad o registro desde el 1-jul', tip="Cada uno tiene un perfil con más de 100 indicadores, disponible en la exportación de la base.")}
    {tile('Recargan y apuestan', n(activos_rec_apu), f'{n(100 * activos_rec_apu / tot_j, 0)} % · casi todo el monto · <a href="#prediccion">Ver riesgo</a>', acc=True)}
    {tile('Registrados sin actividad', n(nuevos_sin), f"{n(100 * nuevos_sin / tot_j, 0)} % · audiencia de ACT01 y ACT05", tip="Se registraron y nunca recargaron ni apostaron. ACT01 cubre los primeros 7 días; ACT05, del día 8 al 30.")}
    {tile('Recargan sin apostar en deportes', n(int(pf[pf.act == 'Solo recarga'].j.sum())), f'{n(pct_sr_cas, 0)} % juega casino · venta cruzada (XS03)')}
  </div>
  <section class="panel"><div class="ph"><h2>Composición por actividad</h2><span class="sub">Jugadores por tipo de actividad, {periodo_txt}</span></div><div class="pb">{f_pf}</div></section>
  <section class="panel"><div class="ph"><h2>Detalle por población y actividad</h2><span class="sub">Totales y medianas por grupo</span></div><div class="pb flush">{t_pf}</div></section>
  <div class="g g2">
    <section class="panel"><div class="ph"><h2>Apostadores por días con apuesta</h2><span class="sub">% del monto apostado de cada grupo</span></div><div class="pb">{f_ia}
      <p class="small muted">{n(ia.j.iloc[-1])} jugadores que apostaron más de 60 de los 92 días concentran el {n(ia.pm.iloc[-1], 0)} % del monto apostado; {n(ia.j.iloc[0])} que apostaron 1 o 2 días aportan el {n(ia.pm.iloc[0], 1)} %.</p></div></section>
    <section class="panel"><div class="ph"><h2>Jugadores por cantidad de recargas</h2><span class="sub">% del monto recargado de cada grupo</span></div><div class="pb">{f_ir}
      <p class="small muted">{n(ir.j.iloc[0])} jugadores hicieron una sola recarga ({n(ir.pm.iloc[0], 1)} % del monto); {n(ir.j.iloc[-1])} hicieron más de 100 ({n(ir.pm.iloc[-1], 0)} %).</p></div></section>
  </div>
  <div class="note"><b>Detalle individual</b><span>El perfil de cada jugador (una fila por jugador, sin teléfono) está en la base y en el Excel de exportación, hoja <code>ficha_jugador</code>. No se incluye en esta aplicación para no exponer identificadores.</span></div>
</section>

<section class="view" id="v-insights" data-title="Insights">
  <div class="vhead"><div><h1>Insights</h1><p>Lo que muestran los datos y qué hacer con cada hallazgo.</p></div></div>
  {insight("Quienes generan el volumen no son quienes podemos contactar", f"{n(pct_apu_hist, 0)} %", "del monto apostado viene de la base sin teléfono",
           f"{n(reg_tot.j)} registrados desde julio traen teléfono; {n(hist.j)} registrados antes solo aparecen en transacciones.",
           f"De los activos de la última semana, {n(rc.sin_datos_contacto.iloc[0])} son de la base histórica y {n(rc.con_datos_contacto.iloc[0])} registrados recientes.",
           "Quienes más apuestan son jugadores antiguos de los que no tenemos teléfono.",
           "Pedir a YAjuego el teléfono y el consentimiento de la base histórica.", f_rc, '<span class="pill crit">Bloqueante</span>')}
  {insight("La activación ocurre en la primera hora o casi nunca", f"{n(pct_24h, 0)} %", "de los que recargan lo hacen en 24 h",
           f"{n(conv_tot, 1)} % de los registrados recargó; {n(pct_1h, 0)} % de ellos en menos de una hora.",
           f"Quien no recargó al día 7: solo {CF['tasa_act05'][1]} lo hace entre los días 7 y 21. Los que verificaron el celular recargan {CF['verif_si']}, frente a {CF['verif_no']} de los que no.",
           "La decisión de recargar se toma al registrarse; después del día 7 casi nadie lo hace.",
           "Enviar ACT01 en las primeras 24-72 h (requiere carga diaria).", f_t1)}
  {insight("La retención temprana es el punto débil", f"{n(ret_ini, 0)} %", f"de los convertidos de {MES_N.get(coh[0], coh[0])} sigue activo en los últimos 30 días",
           f"Conversión a recarga por cohorte: {CF['conv_cohortes']}. {CF['repite']} de los convertidos repite recarga.",
           f"Activos en los últimos 30 días, por cohorte: {ret_txt}.",
           "El jugador nuevo prueba y se va en pocas semanas; la segunda recarga decide si se queda.",
           "Priorizar la segunda recarga (ONB02) sobre recuperar inactivos.", f_emb)}
  {insight(f"{'Casi la mitad' if 40 <= rsa_pct < 50 else 'Una parte importante'} de los nuevos que recargan no apuesta en deportes: juega casino", f"{n(rsa_pct, 0)} %", "de los registrados con recarga no apuesta en deportes",
           f"{n(D['rsa'].sin)} de {n(D['rsa'].con)} registrados con recarga no tienen apuestas deportivas. En toda la base, {n(rsa_m, 0)} % del monto recargado viene de jugadores sin apuestas deportivas.",
           f"Desde el {fd(cas_d0)}, {n(pct_sr_cas, 0)} % de quienes recargan sin apostar en deportes juega casino ({n(hc.sin_dep_cas)} de {n(hc.sin_dep)}).",
           "No son inactivos: su producto es casino. Para ellos, deportes es venta cruzada.",
           "Tratar XS03 como venta cruzada y excluir a quien juega casino a diario.", "", '<span class="pill ok">Confirmado con casino</span>')}
  {insight("En vivo mueve el dinero; las combinadas mueven el volumen", CF["vivo_monto"], "del monto en simples en vivo",
           f"Simples en vivo: {CF['vivo_apuestas']} de las apuestas, mediana {CF['vivo_mediana']}. Combinadas prepartido: {CF['comb_apuestas']} de las apuestas, mediana {CF['comb_mediana']} y {CF['comb_sel']} selecciones.",
           f"{n(D['pref'].n.get('prepartido', 0))} jugadores prefieren prepartido y {n(D['pref'].n.get('en_vivo', 0))} en vivo (≥ 5 apuestas). {n(100 * D['bono'].p, 1)} % usa fondos de bono.",
           "Dos perfiles: ticket pequeño con muchas selecciones, y seguimiento del partido con montos mayores.",
           "Usar la variante de mensaje según preferencia: en vivo o prepartido.", f_mix)}
  {insight("Sábado al mediodía es el pico", n(dow[6]), "apuestas promedio los sábados",
           f"Lunes: {n(dow[1])} apuestas por día. Pico horario 12-16 h; las recargas siguen el mismo patrón.", "Horario permitido por la Ley 2300 de 2023: lun-vie 7-19 h, sáb 8-15 h.",
           "La actividad sigue el calendario del fútbol de fin de semana.",
           "Enviar de jueves a sábado antes de las 15 h.", f_hm)}
  {insight("La actividad está muy concentrada", f"{n(conc[('Monto apostado', 1)], 0)} %", "del monto apostado en el 1 % de apostadores",
           f"10 % de los apostadores = {n(conc[('Monto apostado', 10)], 0)} % del monto. En recargas: {n(conc[('Monto recargado', 1)], 0)} % y {n(conc[('Monto recargado', 10)], 0)} %.",
           f"Recarga mediana {CF['recarga_mediana']}; p90 de monto recargado por jugador ${n(D['params_base']['valor_p90'])}.",
           "Un grupo pequeño de alta intensidad pesa mucho en cualquier promedio.",
           "Reportar medianas y no presionar más recargas a los de mayor valor.", f_lor)}
  <section class="panel"><div class="ph"><h2>Comparación mensual en base diaria</h2><span class="sub">Promedio por día completo de cada fuente</span></div><div class="pb flush">{t_mes.replace('<div class="tw">', '<div class="tw">', 1)}</div></section>
  <div class="g g2">
    <section class="panel"><div class="ph"><h2>Medios de recarga</h2></div><div class="pb flush">{t_met}</div></section>
    <section class="panel"><div class="ph"><h2>Lo apostado menos lo pagado</h2><span class="sub">Apuestas deportivas liquidadas</span></div><div class="pb">
      <div class="big">{mm(res.ap - res.pg)}</div>
      <p class="small muted">{n(hold, 1)} % de lo apostado en deportes.</p></div></section>
  </div>
</section>

<section class="view" id="v-segmentos" data-title="Segmentos">
  <div class="vhead"><div><h1>Segmentos</h1><p>Un ciclo de vida por jugador, al {corte:%d-%m-%Y}.{info(f"Se asigna en orden de prioridad. 14 días ≈ intervalo habitual entre apuestas (p85). Casino entra desde el {fd(cas_d0)}: quien solo jugó casino antes puede verse inactivo.")}</p></div></div>
  <section class="panel"><div class="ph"><h2>Ciclo de vida</h2></div><div class="pb">{f_cv}</div></section>
  <section class="panel"><div class="ph"><h2>Catálogo de segmentos</h2></div><div class="pb flush">{t_seg}</div></section>
  <section class="panel"><div class="ph"><h2>Etiquetas</h2><span class="sub">Un jugador puede tener varias</span></div><div class="pb flush">{t_hip}</div></section>
  <div class="g g2">
    <div class="note"><b>Protección de juego responsable</b><span>Sale de toda campaña promocional quien tenga {int(P['rec_max_dia_p99'])}+ recargas en un día (p99), ≥ 50 % de recargas de madrugada, o una escalada de monto ≥ 3× sobre el p90. La caída de frecuencia no se usa para reactivar y los retiros no son disparadores.</span></div>
    <div class="note"><b>Contactabilidad</b><span>Solo es contactable quien está en Registros, con cuenta en estado 1, teléfono válido no compartido y edad ≥ 18. Toda audiencia queda bloqueada hasta cruzar consentimiento y autoexclusión.</span></div>
  </div>
</section>

{pred_html}

<section class="view" id="v-audiencias" data-title="Constructor de audiencias">
  <div class="vhead"><div><h1>Constructor de audiencias</h1><p>Arma una audiencia y mira cuántos jugadores alcanza antes de lanzar.</p></div>
    <button type="button" class="btn" id="ab-reset">Restablecer filtros</button></div>
  <div class="g g-73" id="builder">
    <section class="panel"><div class="ph"><h2>Filtros</h2></div><div class="pb">
      <div class="g g3" style="gap:20px">
        <div class="fgroup"><h4>Ciclo de vida</h4><div class="checks">{ck_cv}</div></div>
        <div class="fgroup"><h4>Nivel de valor</h4><div class="checks">{ck_nv}</div></div>
        <div class="fgroup"><h4>Preferencia deportiva</h4><div class="checks">{ck_pm}</div></div>
      </div>
      <div class="g g2" style="gap:20px">
        <div class="fgroup"><h4>Predicción: abandono y activación</h4><div class="checks">{ck_pr}</div></div>
        <div class="fgroup"><h4>Predicción: crecimiento</h4><div class="checks">{ck_op}</div></div>
      </div>
      <div class="fgroup"><h4>Exclusiones</h4><div class="checks">
        <label><input type="checkbox" id="f-cont" checked> Solo contactables con los datos disponibles</label>
        <label><input type="checkbox" id="f-jr" checked> Excluir señales de juego responsable</label></div></div>
    </div></section>
    <section class="panel"><div class="ph"><h2>Audiencia estimada</h2><span class="chip warn">Pendiente de consentimiento</span></div><div class="pb">
      <div class="big" id="ab-n">—</div><span class="muted small" id="ab-pct"></span>
      <div class="bar"><i id="ab-bar" style="width:0"></i></div>
      <div class="g g2" style="gap:10px">
        {tile('Contactables', '<span id="ab-cont">—</span>', 'Teléfono válido y no compartido, cuenta activa. Falta cruzar consentimiento y autoexclusión.')}
        {tile('Recibirían el SMS', '<span id="ab-env">—</span>', 'Otros <span id="ab-ctrl" class="mono">—</span> (20 %) quedan sin mensaje como grupo de control.')}
        {tile('Con señal de juego responsable', '<span id="ab-jr">—</span>', 'Por ejemplo, muchas recargas en un día o de madrugada. Se excluyen de todo mensaje promocional.')}
        {tile('Sin teléfono', '<span id="ab-tel">—</span>', 'Registrados antes de julio: no se pueden contactar con los datos actuales.')}
      </div>
      <p class="small muted">Los números junto a cada opción muestran cuántos jugadores aporta con el resto de filtros activos.</p>
    </div></section>
  </div>
</section>

<section class="view" id="v-octubre" data-title="Tendencias y casino">
  <div class="vhead"><div><h1>Tendencias y casino</h1><p>Cómo evoluciona la actividad semana a semana y qué pasa en casino.</p></div></div>
  <section class="panel"><div class="ph"><h2>Promedio diario por semana</h2>{info("Promedio por día con datos completos de cada producto.")}</div><div class="pb">{f_sem}</div></section>
  <section class="panel"><div class="ph"><h2>Detalle por semana</h2><span class="sub">La más reciente primero</span></div><div class="pb flush">{t_pd}</div></section>
  <div class="g g4">
    {tile('Rondas de casino', n(cas.rondas), f"{n(cas.jug)} jugadores · {n(cas.juegos)} juegos")}
    {tile('Apostado en casino', mm(cas.ap), f"{n(cas_mismos / dep_mismos, 1)} veces lo de deportes", acc=True, tip="Comparación en los días con datos completos de ambos productos.")}
    {tile('Premios pagados', mm(cas.pg), f"{n(100 * cas.pg / cas.ap, 1)} % de lo apostado vuelve al jugador")}
    {tile('Concentración', f"{n(D['cas_top'].t1, 0)}<small> %</small>", f"del monto en el 1 % de jugadores", tip=f"El 10 % más activo concentra el {n(D['cas_top'].t10, 0)} %. Pocos jugadores mueven el promedio: usa medianas.")}
  </div>
  {insight("Quien recarga y no apuesta en deportes juega casino", f"{n(pct_sr_cas, 0)} %", f"de quienes recargan sin apostar en deportes juega casino",
           f"Desde el {fd(cas_d0)}, {n(hc.recargan)} jugadores recargaron; {n(hc.sin_dep)} no apostaron en deportes y {n(hc.sin_dep_cas)} de ellos jugaron casino. Otros {n(hc.dep_cas)} juegan ambos productos.",
           f"{cas_txt}; se mide solo en días con datos de casino.",
           "No son inactivos: juegan casino. Deportes es venta cruzada.",
           "En XS03, excluir o diferenciar a quien juega casino a diario.", "", f'<span class="pill ok">Validado con {dias_cas} días</span>')}
  <div class="g g2">
    <section class="panel"><div class="ph"><h2>Proveedores de casino</h2><span class="sub">% del monto apostado · {cas_txt}</span></div><div class="pb">{f_cas_prov}</div></section>
    <section class="panel"><div class="ph"><h2>Rondas de casino por hora</h2><span class="sub">{cas_txt} · hora del archivo</span></div><div class="pb">{f_cas_hora}
      <p class="small muted">Pico de noche y madrugada, al revés que deportes: vigilar en las señales de juego responsable.</p></div></section>
  </div>
  <section class="panel"><div class="ph"><h2>¿Quién juega casino?</h2></div><div class="pb flush"><div class="list">
    <div class="li"><span class="ic warn">{n(100 * cb.get('Base anterior a julio', 0) / cas.jug, 0)}%</span><div><b>{n(cb.get('Base anterior a julio', 0))} de la base anterior a julio</b><span>Sin teléfono en los archivos recibidos.</span></div><span></span></div>
    <div class="li"><span class="ic acc">{n(100 * cb.get('Registrados desde julio', 0) / cas.jug, 0)}%</span><div><b>{n(cb.get('Registrados desde julio', 0))} registrados desde julio</b><span>Con datos de contacto.</span></div><span></span></div>
  </div></div></section>
</section>

{vistas_activacion}

<section class="view" id="v-ajustes" data-title="Pendientes">
  <div class="vhead"><div><h1>Pendientes de YAjuego</h1><p>Lo que falta para enviar, llegar a más jugadores y afinar los segmentos.</p></div></div>
  <div class="g g3">
    {tile('Bloquean el envío', str(len(PEND['envio'])), 'Sin esto ninguna campaña sale', acc=True)}
    {tile('Amplían el alcance', str(len(PEND['alcance'])), 'Más jugadores y campañas a tiempo')}
    {tile('Afinan los segmentos', str(len(PEND['precision'])), 'Datos faltantes o por confirmar')}
  </div>
  {pend_html}
  <div class="g g2">
    <section class="panel"><div class="ph"><h2>Riesgos de la propuesta</h2></div><div class="pb flush"><div class="list">
      <div class="li"><span class="ic warn">1</span><div><b>El piloto ataca la población de menor valor</b><span>La mayoría de los envíos va a registrados sin recarga, con conversión natural de {CF['tasa_act05'][1]} a {CF['tasa_act01'][1]}. El control dirá si el SMS paga su costo.</span></div><span></span></div>
      <div class="li"><span class="ic warn">2</span><div><b>Sin carga diaria, la activación llega tarde</b><span>El {n(pct_24h, 0)} % convierte en 24 h. ACT01 no debería operar sin carga diaria.</span></div><span></span></div>
      <div class="li"><span class="ic warn">3</span><div><b>XS03 puede incomodar a jugadores de casino</b><span>Sin casino del 1 al 27-oct no se puede excluir del todo a quien juega casino de forma habitual.</span></div><span></span></div>
      <div class="li"><span class="ic warn">4</span><div><b>Campañas de retención pequeñas</b><span>RET04 y REC06 suman {n(cam.loc['RET04'].seleccionados + cam.loc['REC06'].seleccionados)} jugadores: sirven para probar mensajes, no para concluir.</span></div><span></span></div>
      <div class="li"><span class="ic crit">5</span><div><b>Riesgo regulatorio y reputacional</b><span>Enviar sin consentimiento, fuera de horario o a un autoexcluido cuesta más que cualquier resultado.</span></div><span></span></div>
    </div></div></section>
    <section class="panel"><div class="ph"><h2>Decisiones tomadas</h2></div><div class="pb flush"><div class="list">
      <div class="li"><span class="ic ok">✓</span><div><b>Sin bonos ni promociones</b><span>Si se suman, se confirman con YAjuego y se miden como variante.</span></div><span></span></div>
      <div class="li"><span class="ic ok">✓</span><div><b>Un SMS por jugador por semana</b><span>Cada jugador entra a una sola campaña por ola, la de mayor prioridad.</span></div><span></span></div>
      <div class="li"><span class="ic ok">✓</span><div><b>20 % de cada audiencia como control</b><span>Asignación fija por jugador, para medir el efecto real del SMS.</span></div><span></span></div>
      <div class="li"><span class="ic ok">✓</span><div><b>Señales de juego responsable fuera</b><span>Quien muestra señales de riesgo no recibe mensajes promocionales.</span></div><span></span></div>
    </div></div></section>
  </div>
</section>

  </main>
</div>
</div>
<script type="application/json" id="app-data">{data_json}</script>
<script>{JS}</script>
"""
    return body


def main():
    D = cargar_app(cargar())
    out = REPORT_DIR / "informe_yajuego.html"
    out.write_text(ocultar_modulos(construir_html(D)), encoding="utf-8")
    print(f"[ok] app: {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
