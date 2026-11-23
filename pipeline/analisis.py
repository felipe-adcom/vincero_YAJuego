"""Análisis descriptivo: tablas (CSV) y gráficos (PNG) sin datos personales.

Se regenera en cada corrida de run.py. Describe el periodo base (último mes completo,
config.FIN_ANALISIS) para no mezclar meses parciales; el ciclo de vida usa el corte operativo.
Salidas en reports/tablas/ y reports/figuras/.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from config import REPORT_DIR  # noqa: E402

S1, S2 = "#0A0A0B", "#2F5BFF"
TXT, TXT2, GRID, SURF = "#0A0A0B", "#5B5B62", "#ECECEA", "#FFFFFF"
SEQ = ["#EEF2FF", "#D3DDFF", "#A9BCFF", "#7B97FF", "#4F70F5", "#2D4FD6", "#1A329E"]

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": TXT2, "xtick.color": TXT2, "ytick.color": TXT2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": TXT, "axes.titlelocation": "left",
    "legend.frameon": False,
})


def _save(fig, nombre):
    fig.tight_layout()
    fig.savefig(REPORT_DIR / "figuras" / nombre, dpi=150)
    plt.close(fig)


def _tabla(con, nombre, sql):
    df = con.execute(sql).df()
    df.to_csv(REPORT_DIR / "tablas" / f"{nombre}.csv", index=False)
    return df


def _miles(x, _=None):
    return f"{x:,.0f}".replace(",", ".")


def generar_reporte(con):
    (REPORT_DIR / "figuras").mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "tablas").mkdir(parents=True, exist_ok=True)
    M = "base.jugador_resumen"   # análisis descriptivo: foto al último mes completo
    # El análisis describe la ventana hasta el fin del periodo base; lo posterior va al módulo de seguimiento.
    for vista, tabla, col in [("v_recarga", "core.recarga", "fecha_hora"), ("v_apuesta", "core.apuesta", "fecha_hora"),
                              ("v_retiro", "core.retiro", "fecha_ultima_actualizacion"), ("v_registro", "core.registro", "fecha_registro")]:
        con.execute(f"CREATE OR REPLACE TEMP VIEW {vista} AS SELECT * FROM {tabla} WHERE {col} <= getvariable('fin_analisis')")

    _tabla(con, "01_cobertura_fuentes", f"""
        SELECT CASE WHEN en_registros THEN 'Registrados jul-sep (con datos de contacto)'
                    ELSE 'Base anterior a julio (sin datos de contacto)' END AS poblacion,
               count(*) jugadores, sum((rec_n>0)::INT) con_recarga, sum((apu_n>0)::INT) con_apuesta,
               sum((ret_n>0)::INT) con_retiro, sum(rec_n) recargas, sum(rec_monto) monto_recargas,
               sum(apu_n) apuestas, sum(apu_monto) monto_apostado,
               round(100*sum(apu_monto)/sum(sum(apu_monto)) OVER (), 1) pct_monto_apostado
        FROM {M} GROUP BY 1 ORDER BY 1 DESC""")

    emb = _tabla(con, "02_embudo_cohortes", f"""
        SELECT cohorte_registro, count(*) registrados,
               sum((rec_n>0)::INT) con_recarga, round(100*avg((rec_n>0)::INT),1) pct_recarga,
               sum((apu_n>0)::INT) con_apuesta, round(100*avg((apu_n>0)::INT),1) pct_apuesta,
               sum((rec_n>1)::INT) con_2_recargas,
               round(100*sum((rec_n>1)::INT)/nullif(sum((rec_n>0)::INT),0),1) pct_repite_de_convertidos,
               round(100*avg((rec_n>0 AND apu_n=0)::INT),1) pct_recarga_sin_apuesta_deportiva,
               median(horas_registro_a_primera_recarga) mediana_horas_a_1a_recarga,
               round(100*avg(CASE WHEN rec_n>0 THEN (horas_registro_a_primera_recarga<24)::INT END),1) pct_convertidos_en_24h
        FROM {M} WHERE historia_completa GROUP BY 1 ORDER BY 1""")
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    x = np.arange(len(emb))
    w = 0.36
    b1 = ax.bar(x - w / 2 - 0.01, emb.pct_recarga, w, color=S1, label="Recargó")
    b2 = ax.bar(x + w / 2 + 0.01, emb.pct_apuesta, w, color=S2, label="Apostó en deportes")
    for bars in (b1, b2):
        ax.bar_label(bars, fmt="%.1f%%", padding=2, color=TXT, fontsize=9)
    ax.set_xticks(x, [f"{c}\n({_miles(n)} registros)" for c, n in zip(emb.cohorte_registro, emb.registrados)])
    ax.set_ylabel("% de registrados")
    ax.set_title("Conversión observada por cohorte de registro")
    ax.legend(loc="upper right", ncols=2)
    ax.set_ylim(0, max(emb.pct_recarga) * 1.3)
    _save(fig, "01_embudo_cohortes.png")

    t = _tabla(con, "03_tiempo_primera_recarga", f"""
        SELECT CASE WHEN horas_registro_a_primera_recarga < 1 THEN '1. < 1 hora'
                    WHEN horas_registro_a_primera_recarga < 24 THEN '2. 1-24 horas'
                    WHEN horas_registro_a_primera_recarga < 168 THEN '3. 1-7 días'
                    WHEN horas_registro_a_primera_recarga < 720 THEN '4. 7-30 días'
                    ELSE '5. > 30 días' END tramo,
               count(*) jugadores, round(100*count(*)/sum(count(*)) OVER (),1) pct
        FROM {M} WHERE historia_completa AND rec_n>0 GROUP BY 1 ORDER BY 1""")
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    bars = ax.bar([s[3:] for s in t.tramo], t.pct, color=S2, width=0.6)
    ax.bar_label(bars, labels=[f"{p:.0f}%  ({_miles(n)})" for p, n in zip(t.pct, t.jugadores)], padding=2, color=TXT, fontsize=9)
    ax.set_ylabel("% de quienes recargaron")
    ax.set_title("Tiempo entre registro y primera recarga")
    ax.set_ylim(0, t.pct.max() * 1.25)
    _save(fig, "02_tiempo_primera_recarga.png")

    d = _tabla(con, "04_actividad_diaria", """
        SELECT r.dia, r.recargas, r.monto_recargas, a.apuestas, a.monto_apostado, a.apostadores
        FROM (SELECT fecha_hora::DATE dia, count(*) recargas, sum(monto) monto_recargas FROM v_recarga GROUP BY 1) r
        JOIN (SELECT fecha_hora::DATE dia, count(*) apuestas, sum(monto_apostado) monto_apostado,
                     count(DISTINCT player_id) apostadores FROM v_apuesta GROUP BY 1) a USING (dia)
        ORDER BY dia""")
    fig, axs = plt.subplots(2, 1, figsize=(8, 4.6), sharex=True)
    for ax, col, titulo in [(axs[0], "apuestas", "Apuestas deportivas por día"), (axs[1], "recargas", "Recargas por día")]:
        ax.plot(d.dia, d[col], color=S1, linewidth=2)
        sab = d[d.dia.map(lambda x: x.isoweekday() == 6)]
        ax.scatter(sab.dia, sab[col], s=22, color=S2, edgecolor=SURF, linewidth=1.5, zorder=3, label="sábado")
        ax.set_title(titulo, fontsize=11)
        ax.yaxis.set_major_formatter(_miles)
    axs[0].legend(loc="upper left")
    _save(fig, "03_actividad_diaria.png")

    _tabla(con, "05_comparacion_mensual", """
        WITH r AS (SELECT strftime(fecha_hora,'%Y-%m') mes, count(*) recargas, sum(monto) monto_recargas,
                          count(DISTINCT player_id) jugadores_recarga, count(DISTINCT fecha_hora::DATE) dias FROM v_recarga GROUP BY 1),
             a AS (SELECT strftime(fecha_hora,'%Y-%m') mes, count(*) apuestas, sum(monto_apostado) monto_apostado,
                          count(DISTINCT player_id) apostadores FROM v_apuesta GROUP BY 1),
             t AS (SELECT strftime(fecha_ultima_actualizacion,'%Y-%m') mes, count(*) retiros, sum(monto_neto) monto_retiros,
                          count(DISTINCT player_id) jugadores_retiro FROM v_retiro GROUP BY 1),
             g AS (SELECT strftime(fecha_registro,'%Y-%m') mes, count(*) registros FROM v_registro GROUP BY 1)
        SELECT mes, dias, registros, round(registros/dias) registros_dia,
               recargas, round(recargas/dias) recargas_dia, round(monto_recargas/dias) monto_recargas_dia, jugadores_recarga,
               apuestas, round(apuestas/dias) apuestas_dia, round(monto_apostado/dias) monto_apostado_dia, apostadores,
               retiros, round(monto_retiros/dias) monto_retiros_dia, jugadores_retiro
        FROM r JOIN a USING (mes) JOIN t USING (mes) JOIN g USING (mes) ORDER BY mes""")

    rc = _tabla(con, "06_recencia_contacto", f"""
        SELECT CASE WHEN dias_desde_ultima_actividad <= 7 THEN '0-7'
                    WHEN dias_desde_ultima_actividad <= 14 THEN '8-14'
                    WHEN dias_desde_ultima_actividad <= 30 THEN '15-30'
                    WHEN dias_desde_ultima_actividad <= 60 THEN '31-60'
                    ELSE '61-92' END tramo_dias,
               sum((NOT en_registros)::INT) sin_datos_contacto, sum(en_registros::INT) con_datos_contacto
        FROM {M} WHERE ultima_actividad_obs IS NOT NULL GROUP BY 1
        ORDER BY min(dias_desde_ultima_actividad)""")
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    x = np.arange(len(rc))
    b1 = ax.bar(x - w / 2 - 0.01, rc.sin_datos_contacto, w, color=S1, label="Base anterior a julio (sin teléfono en archivos)")
    b2 = ax.bar(x + w / 2 + 0.01, rc.con_datos_contacto, w, color=S2, label="Registrados jul-sep (con teléfono)")
    for bars in (b1, b2):
        ax.bar_label(bars, labels=[_miles(v) for v in bars.datavalues], padding=2, color=TXT, fontsize=9)
    ax.set_xticks(x, rc.tramo_dias)
    ax.set_xlabel("Días desde la última recarga o apuesta")
    ax.set_ylabel("Jugadores")
    ax.set_title("Recencia de actividad: los más activos no tienen teléfono en los archivos")
    ax.set_ylim(0, max(rc.sin_datos_contacto.max(), rc.con_datos_contacto.max()) * 1.3)
    ax.legend(loc="upper right")
    _save(fig, "04_recencia_contacto.png")

    conc = con.execute(f"SELECT apu_monto, rec_monto FROM {M} WHERE apu_n>0 OR rec_n>0").df()
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    filas = []
    for col, color, nombre in [("apu_monto", S1, "Monto apostado"), ("rec_monto", S2, "Monto recargado")]:
        v = np.sort(conc[col].astype(float).values)[::-1]
        acum = np.cumsum(v) / v.sum()
        pct = np.arange(1, len(v) + 1) / len(v) * 100
        ax.plot(pct, acum * 100, color=color, linewidth=2, label=nombre)
        for p in (1, 5, 10, 20):
            filas.append((nombre, p, round(100 * acum[int(len(v) * p / 100) - 1], 1)))
    ax.set_xlim(0, 30)
    ax.set_ylim(0, 102)
    ax.set_xlabel("% de jugadores con actividad, de mayor a menor (primer 30%)")
    ax.set_ylabel("% acumulado del monto")
    ax.set_title("Concentración de la actividad")
    ax.legend(loc="lower right")
    _save(fig, "05_concentracion.png")
    pd.DataFrame(filas, columns=["medida", "top_pct_jugadores", "pct_del_monto"]).to_csv(
        REPORT_DIR / "tablas" / "07_concentracion.csv", index=False)

    hm = _tabla(con, "08_apuestas_dia_hora", """
        SELECT isodow(fecha_hora) dia_semana, hour(fecha_hora) hora,
               count(*) / count(DISTINCT fecha_hora::DATE) apuestas_promedio_dia
        FROM v_apuesta GROUP BY 1, 2 ORDER BY 1, 2""")
    mat = hm.pivot(index="dia_semana", columns="hora", values="apuestas_promedio_dia").values
    fig, ax = plt.subplots(figsize=(9, 3.2))
    im = ax.imshow(mat, aspect="auto", cmap=LinearSegmentedColormap.from_list("seq", SEQ))
    ax.set_yticks(range(7), ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"])
    ax.set_xticks(range(0, 24, 2), [f"{h}h" for h in range(0, 24, 2)])
    ax.grid(False)
    fig.colorbar(im, ax=ax, pad=0.01).set_label("Apuestas promedio por día", color=TXT2)
    ax.set_title("Apuestas deportivas por día de la semana y hora")
    _save(fig, "06_apuestas_dia_hora.png")

    mix = _tabla(con, "09_mix_apuestas", """
        SELECT CASE WHEN tipo_apuesta='SINGLE' THEN 'Simple' ELSE 'Combinada/sistema' END || ' · ' ||
               CASE live_cod WHEN 0 THEN 'prepartido' WHEN 1 THEN 'en vivo' ELSE 'mixta (cod. 2)' END AS tipo,
               count(*) apuestas, round(100*count(*)/sum(count(*)) OVER (),1) pct_apuestas,
               sum(monto_apostado) monto, round(100*sum(monto_apostado)/sum(sum(monto_apostado)) OVER (),1) pct_monto,
               median(monto_apostado) apuesta_mediana, median(selecciones) selecciones_mediana,
               count(DISTINCT player_id) jugadores
        FROM v_apuesta GROUP BY 1 ORDER BY monto DESC""")
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    y = np.arange(len(mix))
    h = 0.36
    b1 = ax.barh(y - h / 2 - 0.01, mix.pct_apuestas, h, color=S1, label="% de apuestas")
    b2 = ax.barh(y + h / 2 + 0.01, mix.pct_monto, h, color=S2, label="% del monto apostado")
    for bars in (b1, b2):
        ax.bar_label(bars, fmt="%.0f%%", padding=2, color=TXT, fontsize=9)
    ax.set_yticks(y, mix.tipo)
    ax.invert_yaxis()
    ax.set_title("Simples en vivo: el monto. Combinadas: el volumen")
    ax.legend(loc="lower right")
    ax.set_xlim(0, max(mix.pct_apuestas.max(), mix.pct_monto.max()) * 1.2)
    _save(fig, "07_mix_apuestas.png")

    # Ciclo de vida al corte operativo
    cv = _tabla(con, "10_ciclo_vida", """
        SELECT ciclo_vida,
               sum((estado_contacto='contactable_pendiente_consentimiento')::INT) contactables,
               sum((estado_contacto<>'contactable_pendiente_consentimiento')::INT) no_contactables,
               count(*) total, round(100*count(*)/sum(count(*)) OVER (),1) pct
        FROM mart.segmento_jugador GROUP BY 1 ORDER BY 1""")
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = np.arange(len(cv))
    ax.barh(y, cv.contactables, color=S2, label="Contactable con datos disponibles", height=0.6)
    ax.barh(y, cv.no_contactables, left=cv.contactables + cv.total.max() * 0.004, color=S1,
            label="No contactable (sin teléfono, cuenta no activa, etc.)", height=0.6)
    for i, (tot, p) in enumerate(zip(cv.total, cv.pct)):
        ax.text(tot + cv.total.max() * 0.01, i, f"{_miles(tot)} ({p}%)", va="center", color=TXT, fontsize=9)
    ax.set_yticks(y, [c[2:].replace("_", " ") for c in cv.ciclo_vida])
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(_miles)
    ax.set_xlim(0, cv.total.max() * 1.25)
    ax.set_title("Segmentos de ciclo de vida al corte")
    ax.legend(loc="lower right")
    _save(fig, "08_ciclo_vida.png")

    _tabla(con, "11_patron_actividad", f"SELECT patron_actividad, en_registros, count(*) jugadores FROM {M} GROUP BY ALL ORDER BY 3 DESC")
    _tabla(con, "12_metodos_recarga", """
        SELECT metodo, count(*) recargas, round(100*count(*)/sum(count(*)) OVER (),1) pct_recargas,
               sum(monto) monto, median(monto) recarga_mediana, count(DISTINCT player_id) jugadores
        FROM v_recarga GROUP BY 1 ORDER BY 2 DESC""")
    _tabla(con, "13_canal_apuestas", """
        SELECT canal, count(*) apuestas, round(100*count(*)/sum(count(*)) OVER (),1) pct, count(DISTINCT player_id) jugadores
        FROM v_apuesta GROUP BY 1 ORDER BY 2 DESC""")
    _tabla(con, "14_retiros_procesamiento", """
        SELECT metodo, count(*) retiros, sum(monto_neto) monto_neto, median(monto_neto) retiro_mediano,
               median(minutos_hasta_actualizacion) minutos_mediana,
               quantile_cont(minutos_hasta_actualizacion, 0.9) minutos_p90
        FROM v_retiro GROUP BY 1 ORDER BY 2 DESC""")
    # Resultado agregado de apuestas liquidadas (contexto: NO es GGR/NGR)
    _tabla(con, "15_resultado_agregado_apuestas", """
        SELECT strftime(fecha_hora,'%Y-%m') mes, estado_ticket, count(*) tickets,
               sum(monto_apostado) monto_apostado, sum(monto_ganado) pagado_al_jugador,
               sum(monto_apostado) - sum(monto_ganado) diferencia_bruta,
               sum(monto_apostado) FILTER (WHERE con_fondos_bono=1) monto_con_fondos_bono
        FROM v_apuesta GROUP BY ALL ORDER BY 1, 2""")
    print("[ok] reporte de análisis: reports/figuras y reports/tablas")
