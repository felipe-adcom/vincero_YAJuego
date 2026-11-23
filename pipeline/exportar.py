"""Exportes.

data/exports/ (contiene datos personales: no se versiona)
  - jugador_ficha_<corte>.csv      una fila por jugador: ficha analítica + segmentos (sin teléfono)
  - audiencias/<campaña>_<corte>.csv  audiencia operativa mínima (incluye teléfono)
  - yajuego_crm_<corte>.xlsx       los mismos datos en un libro de Excel
reports/ (agregados, sin datos personales)
  - segmentos_tamano.csv, hipersegmentos_tamano.csv, campanas_tamano.csv, embudo_audiencias.csv
"""
import pandas as pd

from config import EXPORT_DIR, REPORT_DIR

FICHA_SQL = """
SELECT j.* EXCLUDE (telefono_10, telefono_estado, jugadores_mismo_telefono),
       j.telefono_10 IS NOT NULL AS tiene_telefono_valido,
       s.* EXCLUDE (player_id, fecha_corte)
FROM mart.jugador_resumen j JOIN mart.segmento_jugador s USING (player_id)
ORDER BY player_id
"""


def exportar(con):
    corte = con.execute("SELECT strftime(getvariable('corte')::TIMESTAMP, '%Y%m%d')").fetchall()[0][0]
    (EXPORT_DIR / "audiencias").mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    ficha = con.execute(FICHA_SQL).df()
    ficha.to_csv(EXPORT_DIR / f"jugador_ficha_{corte}.csv", index=False, encoding="utf-8-sig")

    aud = con.execute("SELECT * FROM mart.audiencia_sms ORDER BY campana, grupo, player_id").df()
    for campana, df in aud.groupby("campana"):
        df.to_csv(EXPORT_DIR / "audiencias" / f"{campana}_{corte}.csv", index=False, encoding="utf-8-sig")

    # Agregados sin datos personales
    seg = con.execute("""
        SELECT ciclo_vida, estado_contacto = 'contactable_pendiente_consentimiento' AS contactable,
               count(*) AS jugadores, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_poblacion
        FROM mart.segmento_jugador GROUP BY ALL ORDER BY 1, 2""").df()
    seg.to_csv(REPORT_DIR / "segmentos_tamano.csv", index=False)
    hip = con.execute("""
        UNPIVOT (SELECT player_id, h_sin_recarga_0_7d, h_sin_recarga_8_30d, h_sin_recarga_31d_mas,
                        h_deposito_posterior_al_corte, h_recarga_sin_apuesta_deportiva, h_una_sola_recarga,
                        h_atrasado_vs_ritmo_propio, h_caida_de_frecuencia, h_retorno, h_continuo_3_ventanas,
                        senal_revision_juego_responsable,
                        estado_contacto = 'contactable_pendiente_consentimiento' AS contactable
                 FROM mart.segmento_jugador)
        ON COLUMNS(* EXCLUDE (player_id, contactable)) INTO NAME etiqueta VALUE activo""").df()
    hip = (hip[hip.activo].groupby("etiqueta")
           .agg(jugadores=("player_id", "count"), contactables=("contactable", "sum")).reset_index())
    hip["pct_poblacion"] = (100 * hip.jugadores / len(ficha)).round(2)
    hip.to_csv(REPORT_DIR / "hipersegmentos_tamano.csv", index=False)
    emb = con.execute("""
        SELECT campana, resultado, grupo, count(*) AS jugadores
        FROM mart.audiencia_sms_detalle GROUP BY ALL ORDER BY 1, 2, 3""").df()
    emb.to_csv(REPORT_DIR / "embudo_audiencias.csv", index=False)
    cam = con.execute("""
        SELECT k.campana, k.prioridad, k.nombre, k.pct_control,
               count(*) FILTER (WHERE d.player_id IS NOT NULL) AS candidatos,
               count(*) FILTER (WHERE resultado = 'seleccionado') AS seleccionados,
               count(*) FILTER (WHERE resultado = 'seleccionado' AND grupo = 'envio') AS envio,
               count(*) FILTER (WHERE resultado = 'seleccionado' AND grupo = 'control') AS control
        FROM mart.campana_catalogo k LEFT JOIN mart.audiencia_sms_detalle d USING (campana)
        GROUP BY ALL ORDER BY k.prioridad""").df()
    cam.to_csv(REPORT_DIR / "campanas_tamano.csv", index=False)

    with pd.ExcelWriter(EXPORT_DIR / f"yajuego_crm_{corte}.xlsx", engine="openpyxl") as xw:
        cam.to_excel(xw, sheet_name="campanas", index=False)
        aud.to_excel(xw, sheet_name="audiencias_sms", index=False)
        ficha.to_excel(xw, sheet_name="ficha_jugador", index=False)
        seg.to_excel(xw, sheet_name="segmentos", index=False)
        hip.to_excel(xw, sheet_name="hipersegmentos", index=False)
    print(f"[ok] exportes: {len(ficha)} jugadores, {len(aud)} filas de audiencia")
