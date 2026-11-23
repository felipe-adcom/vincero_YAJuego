"""Controles de conciliación origen → staging → core → mart → audiencias.

Cada control compara una cantidad o monto entre capas. Resultado:
  OK     cuadra exactamente (o la diferencia está explicada por la regla del control)
  FALLA  no cuadra: hay que investigar antes de usar los resultados
  INFO   dato de contexto (no se espera igualdad)
"""
import pandas as pd

from config import REPORT_DIR

ACTIVAS = "(SELECT load_id FROM meta.manifiesto WHERE estado='cargado')"


def _v(con, sql):
    return con.execute(sql).fetchall()[0][0]


def ejecutar_controles(con):
    filas = []

    def add(control, esperado, obtenido, estado=None, nota=""):
        if estado is None:
            estado = "OK" if esperado == obtenido else "FALLA"
        filas.append(dict(control=control, esperado=str(esperado), obtenido=str(obtenido), estado=estado, nota=nota))

    # 1. Archivo -> staging: filas leídas de cada archivo == filas en staging
    for load_id, archivo, fuente, n in con.execute(
            "SELECT load_id, archivo, fuente, filas FROM meta.manifiesto WHERE fuente IS NOT NULL ORDER BY load_id").fetchall():
        add(f"filas archivo→staging: {archivo}", n, _v(con, f"SELECT count(*) FROM stg.{fuente} WHERE _load_id={load_id}"))
    for archivo, nota in con.execute("SELECT archivo, nota FROM meta.manifiesto WHERE estado IN ('duplicado_exacto','reemplazado','no_reconocido')").fetchall():
        add(f"archivo no usado en core: {archivo}", "-", "-", "INFO", nota)

    # 2. Staging activo -> core: filas y llaves únicas. La diferencia solo puede venir de llaves repetidas.
    pares = [("registros", "id", "core.registro", None),
             ("recargas", "id", "core.recarga", "amount"),
             ("retiros", "id", "core.retiro", "net_amount"),
             ("apuestas", "bet_id, bet_type", "core.apuesta_linea", "stake"),
             ("casino", "bet_id", "core.casino", "stake")]
    for fuente, llave, tabla, col_monto in pares:
        n_stg = _v(con, f"SELECT count(*) FROM stg.{fuente} WHERE _load_id IN {ACTIVAS}")
        n_key = _v(con, f"SELECT count(*) FROM (SELECT DISTINCT {llave} FROM stg.{fuente} WHERE _load_id IN {ACTIVAS})")
        n_core = _v(con, f"SELECT count(*) FROM {tabla}")
        add(f"llaves únicas staging→{tabla}", n_key, n_core,
            nota=f"{n_stg} filas activas en staging; {n_stg - n_key} repetidas por llave ({llave}) se consolidan en una")
        if col_monto:
            m_stg = _v(con, f"""SELECT sum(TRY_CAST({col_monto} AS DECIMAL(18,2))) FROM
                         (SELECT *, row_number() OVER (PARTITION BY {llave} ORDER BY _load_id DESC, _fila) rn
                          FROM stg.{fuente} WHERE _load_id IN {ACTIVAS}) WHERE rn=1""")
            col_core = {"recargas": "monto", "retiros": "monto_neto", "apuestas": "monto_apostado", "casino": "monto_apostado"}[fuente]
            add(f"monto staging→{tabla}", m_stg, _v(con, f"SELECT sum({col_core}) FROM {tabla}"))
        nulos = {"core.recarga": "fecha_hora IS NULL OR monto IS NULL",
                 "core.retiro": "fecha_ultima_actualizacion IS NULL OR monto_neto IS NULL",
                 "core.apuesta_linea": "fecha_hora IS NULL OR monto_apostado IS NULL",
                 "core.casino": "fecha_hora IS NULL OR monto_apostado IS NULL",
                 "core.registro": "fecha_registro IS NULL"}[tabla]
        add(f"valores no convertibles en {tabla}", 0, _v(con, f"SELECT count(*) FROM {tabla} WHERE {nulos}"))

    # 3. Líneas -> tickets de apuestas
    add("apuestas: líneas→tickets conservan el monto",
        _v(con, "SELECT sum(monto_apostado) FROM core.apuesta_linea"), _v(con, "SELECT sum(monto_apostado) FROM core.apuesta"))
    add("apuestas: tickets == bet_id distintos",
        _v(con, "SELECT count(DISTINCT bet_id) FROM core.apuesta_linea"), _v(con, "SELECT count(*) FROM core.apuesta"))

    # 4. Core -> mart: la ficha por jugador no multiplica ni pierde operaciones
    corte = "getvariable('corte')"
    checks = [
        ("recargas (cantidad)", f"SELECT count(*) FROM core.recarga WHERE fecha_hora <= {corte}", "SELECT sum(rec_n) FROM mart.jugador_resumen"),
        ("recargas (monto)", f"SELECT sum(monto) FROM core.recarga WHERE fecha_hora <= {corte}", "SELECT sum(rec_monto) FROM mart.jugador_resumen"),
        ("apuestas (cantidad)", f"SELECT count(*) FROM core.apuesta WHERE fecha_hora <= {corte}", "SELECT sum(apu_n) FROM mart.jugador_resumen"),
        ("apuestas (monto)", f"SELECT sum(monto_apostado) FROM core.apuesta WHERE fecha_hora <= {corte}", "SELECT sum(apu_monto) FROM mart.jugador_resumen"),
        ("casino (rondas)", f"SELECT count(*) FROM core.casino WHERE fecha_hora <= {corte}", "SELECT sum(cas_n) FROM mart.jugador_resumen"),
        ("retiros (cantidad)", f"SELECT count(*) FROM core.retiro WHERE fecha_ultima_actualizacion <= {corte}", "SELECT sum(ret_n) FROM mart.jugador_resumen"),
        ("retiros (monto neto)", f"SELECT sum(monto_neto) FROM core.retiro WHERE fecha_ultima_actualizacion <= {corte}", "SELECT sum(ret_monto_neto) FROM mart.jugador_resumen"),
    ]
    for nombre, a, b in checks:
        add(f"core→mart {nombre}", _v(con, a), _v(con, b))
    add("mart: una fila por jugador", _v(con, "SELECT count(DISTINCT player_id) FROM mart.jugador_resumen"),
        _v(con, "SELECT count(*) FROM mart.jugador_resumen"))
    add("mart: jugadores existentes al corte", _v(con, f"""SELECT count(*) FROM core.jugador j WHERE j.fecha_registro <= {corte}
            OR player_id IN (SELECT player_id FROM core.recarga WHERE fecha_hora <= {corte})
            OR player_id IN (SELECT player_id FROM core.apuesta WHERE fecha_hora <= {corte})
            OR player_id IN (SELECT player_id FROM core.casino WHERE fecha_hora <= {corte})
            OR player_id IN (SELECT player_id FROM core.retiro WHERE fecha_ultima_actualizacion <= {corte})"""),
        _v(con, "SELECT count(*) FROM mart.jugador_resumen"),
        nota="Universo del corte; los jugadores vistos solo después del corte no entran en la foto")
    add("segmentos: una fila por jugador", _v(con, "SELECT count(*) FROM mart.jugador_resumen"),
        _v(con, "SELECT count(*) FROM mart.segmento_jugador"))

    # 5. Audiencias
    add("audiencia: un jugador en máximo una campaña", 0,
        _v(con, "SELECT count(*) FROM (SELECT player_id FROM mart.audiencia_sms GROUP BY 1 HAVING count(*) > 1)"))
    add("audiencia: teléfonos de 10 dígitos que inician en 3", 0,
        _v(con, "SELECT count(*) FROM mart.audiencia_sms WHERE NOT regexp_full_match(coalesce(telefono,''), '3[0-9]{9}')"))
    add("audiencia: sin cuentas no activas, señales JR ni teléfonos compartidos", 0,
        _v(con, """SELECT count(*) FROM mart.audiencia_sms a JOIN mart.segmento_jugador s USING (player_id)
                   WHERE s.estado_contacto <> 'contactable_pendiente_consentimiento' OR s.senal_revision_juego_responsable"""))

    # 6. Contexto
    add("registros de prueba (Test=1) en core", 0,
        _v(con, "SELECT (SELECT count(*) FROM core.recarga WHERE es_prueba=1) + (SELECT count(*) FROM core.apuesta WHERE es_prueba=1) + (SELECT count(*) FROM core.registro WHERE es_prueba=1)"),
        nota="Si aparecen, se excluyen de la ficha por jugador")
    add("operaciones posteriores al corte (excluidas de la ficha)", "-",
        _v(con, f"SELECT (SELECT count(*) FROM core.recarga WHERE fecha_hora > {corte}) + (SELECT count(*) FROM core.apuesta WHERE fecha_hora > {corte})"), "INFO")

    df = pd.DataFrame(filas)
    con.execute("CREATE OR REPLACE TABLE meta.controles AS SELECT current_timestamp AS ejecutado_en, * FROM df")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(REPORT_DIR / "controles.csv", index=False, encoding="utf-8")
    fallas = int((df.estado == "FALLA").sum())
    print(f"[ok] controles: {len(df)} ejecutados, {fallas} fallas")
    return fallas
