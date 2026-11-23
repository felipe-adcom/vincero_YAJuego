-- =====================================================================
-- Capa MART: ficha analítica por jugador al corte.
-- Requiere las variables `corte` e `inicio` (las fija pipeline/run.py desde config.py).
-- Cada métrica se agrega primero dentro de su fuente y luego se une por player_id
-- (1 a 1), para que los cruces nunca multipliquen operaciones ni montos.
--
-- Convenciones:
--   * 0      = se observó al jugador en la ventana y no tuvo esa actividad.
--   * NULL   = desconocido / no aplica (p. ej. fecha de registro no disponible).
--   * "_obs" = primera/última operación OBSERVADA en la ventana, no histórica.
-- Ventanas comparables de 30 días contadas hacia atrás desde el corte:
--   v1 = (corte-30d, corte], v2 = (corte-60d, corte-30d], v3 = (corte-90d, corte-60d]
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS mart;

CREATE OR REPLACE TEMP MACRO ventana(ts) AS
    CASE WHEN ts >  getvariable('corte') - INTERVAL 30 DAY THEN 1
         WHEN ts >  getvariable('corte') - INTERVAL 60 DAY THEN 2
         WHEN ts >  getvariable('corte') - INTERVAL 90 DAY THEN 3 END;

CREATE OR REPLACE TEMP MACRO franja(ts) AS
    CASE WHEN hour(ts) < 6 THEN 'madrugada' WHEN hour(ts) < 12 THEN 'manana'
         WHEN hour(ts) < 18 THEN 'tarde' ELSE 'noche' END;

-- ---------------- Recargas ----------------
CREATE OR REPLACE TEMP TABLE m_rec AS
WITH r AS (SELECT * FROM core.recarga WHERE fecha_hora <= getvariable('corte') AND es_prueba = 0),
dias AS (
    SELECT player_id, d, d - lag(d) OVER (PARTITION BY player_id ORDER BY d) AS gap
    FROM (SELECT DISTINCT player_id, fecha_hora::DATE AS d FROM r)
),
por_dia AS (SELECT player_id, fecha_hora::DATE d, count(*) n FROM r GROUP BY ALL)
SELECT r.player_id,
    count(*)                                   AS rec_n,
    sum(monto)                                 AS rec_monto,
    round(avg(monto), 0)                       AS rec_promedio,
    median(monto)                              AS rec_mediana,
    min(fecha_hora)                            AS rec_primera_obs,
    max(fecha_hora)                            AS rec_ultima_obs,
    count(DISTINCT fecha_hora::DATE)           AS rec_dias_activos,
    count(*) FILTER (WHERE ventana(fecha_hora) = 1) AS rec_n_v1,
    count(*) FILTER (WHERE ventana(fecha_hora) = 2) AS rec_n_v2,
    count(*) FILTER (WHERE ventana(fecha_hora) = 3) AS rec_n_v3,
    coalesce(sum(monto) FILTER (WHERE ventana(fecha_hora) = 1), 0) AS rec_monto_v1,
    coalesce(sum(monto) FILTER (WHERE ventana(fecha_hora) = 2), 0) AS rec_monto_v2,
    coalesce(sum(monto) FILTER (WHERE ventana(fecha_hora) = 3), 0) AS rec_monto_v3,
    count(*) FILTER (WHERE month(fecha_hora) = 7)  AS rec_n_jul,
    count(*) FILTER (WHERE month(fecha_hora) = 8)  AS rec_n_ago,
    count(*) FILTER (WHERE month(fecha_hora) = 9)  AS rec_n_sep,
    mode(metodo)                               AS rec_metodo_principal,
    mode(franja(fecha_hora))                   AS rec_franja_principal,
    round(avg(CASE WHEN hour(fecha_hora) < 6 THEN 1 ELSE 0 END), 3) AS rec_pct_madrugada,
    (SELECT max(n) FROM por_dia p WHERE p.player_id = r.player_id) AS rec_max_en_un_dia,
    (SELECT median(gap) FROM dias g WHERE g.player_id = r.player_id AND gap IS NOT NULL) AS rec_intervalo_mediano_dias
FROM r GROUP BY r.player_id;

-- ---------------- Apuestas deportivas (nivel ticket) ----------------
CREATE OR REPLACE TEMP TABLE m_apu AS
WITH a AS (SELECT * FROM core.apuesta WHERE fecha_hora <= getvariable('corte') AND es_prueba = 0),
dias AS (
    SELECT player_id, d - lag(d) OVER (PARTITION BY player_id ORDER BY d) AS gap
    FROM (SELECT DISTINCT player_id, fecha_hora::DATE AS d FROM a)
)
SELECT a.player_id,
    count(*)                                   AS apu_n,
    sum(monto_apostado)                        AS apu_monto,
    median(monto_apostado)                     AS apu_monto_mediano,
    min(fecha_hora)                            AS apu_primera_obs,
    max(fecha_hora)                            AS apu_ultima_obs,
    count(DISTINCT fecha_hora::DATE)           AS apu_dias_activos,
    count(*) FILTER (WHERE ventana(fecha_hora) = 1) AS apu_n_v1,
    count(*) FILTER (WHERE ventana(fecha_hora) = 2) AS apu_n_v2,
    count(*) FILTER (WHERE ventana(fecha_hora) = 3) AS apu_n_v3,
    count(DISTINCT fecha_hora::DATE) FILTER (WHERE ventana(fecha_hora) = 1) AS apu_dias_v1,
    count(DISTINCT fecha_hora::DATE) FILTER (WHERE ventana(fecha_hora) = 2) AS apu_dias_v2,
    count(DISTINCT fecha_hora::DATE) FILTER (WHERE ventana(fecha_hora) = 3) AS apu_dias_v3,
    count(*) FILTER (WHERE month(fecha_hora) = 7)  AS apu_n_jul,
    count(*) FILTER (WHERE month(fecha_hora) = 8)  AS apu_n_ago,
    count(*) FILTER (WHERE month(fecha_hora) = 9)  AS apu_n_sep,
    round(avg(CASE WHEN live_cod = 1 THEN 1 ELSE 0 END), 3)              AS apu_pct_en_vivo,
    round(avg(CASE WHEN live_cod = 0 THEN 1 ELSE 0 END), 3)              AS apu_pct_prepartido,
    round(avg(CASE WHEN tipo_apuesta = 'SINGLE' THEN 1 ELSE 0 END), 3)   AS apu_pct_simple,
    median(selecciones)                                                  AS apu_selecciones_mediana,
    round(avg(CASE WHEN con_fondos_bono = 1 THEN 1 ELSE 0 END), 3)       AS apu_pct_con_bono,
    round(avg(CASE WHEN cashout = 1 THEN 1 ELSE 0 END), 3)               AS apu_pct_cashout,
    round(avg(CASE WHEN isodow(fecha_hora) >= 6 THEN 1 ELSE 0 END), 3)   AS apu_pct_fin_de_semana,
    mode(canal)                                AS apu_canal_principal,
    mode(franja(fecha_hora))                   AS apu_franja_principal,
    mode(isodow(fecha_hora))                   AS apu_dia_semana_principal,   -- 1=lunes ... 7=domingo
    (SELECT median(gap) FROM dias g WHERE g.player_id = a.player_id AND gap IS NOT NULL) AS apu_intervalo_mediano_dias
FROM a GROUP BY a.player_id;

-- ---------------- Casino (disponible desde octubre de 2026) ----------------
CREATE OR REPLACE TEMP TABLE m_cas AS
SELECT player_id,
    count(*)                                   AS cas_n,
    sum(monto_apostado)                        AS cas_monto,
    count(DISTINCT fecha_hora::DATE)           AS cas_dias_activos,
    min(fecha_hora)                            AS cas_primera_obs,
    max(fecha_hora)                            AS cas_ultima_obs,
    count(*) FILTER (WHERE ventana(fecha_hora) = 1) AS cas_n_v1,
    count(*) FILTER (WHERE ventana(fecha_hora) = 2) AS cas_n_v2,
    count(*) FILTER (WHERE ventana(fecha_hora) = 3) AS cas_n_v3,
    mode(proveedor)                            AS cas_proveedor_principal,
    mode(juego)                                AS cas_juego_principal
FROM core.casino
WHERE fecha_hora <= getvariable('corte') AND es_prueba = 0
GROUP BY player_id;

-- ---------------- Retiros ----------------
CREATE OR REPLACE TEMP TABLE m_ret AS
SELECT player_id,
    count(*)                         AS ret_n,
    sum(monto_neto)                  AS ret_monto_neto,
    min(fecha_solicitud)             AS ret_primera_obs,
    max(fecha_solicitud)             AS ret_ultima_obs,
    median(minutos_hasta_actualizacion) AS ret_minutos_mediana,
    mode(metodo)                     AS ret_metodo_principal
FROM core.retiro
WHERE fecha_ultima_actualizacion <= getvariable('corte') AND es_prueba = 0
GROUP BY player_id;

-- ---------------- Ficha por jugador ----------------
CREATE OR REPLACE TABLE mart.jugador_resumen AS
SELECT
    j.player_id,
    getvariable('corte')::TIMESTAMP                          AS fecha_corte,
    -- Registro y antigüedad
    j.en_registros, j.fecha_registro, j.fuente_fecha_registro,
    CASE WHEN j.fecha_registro IS NULL THEN 'desconocida'
         WHEN j.fecha_registro < getvariable('inicio') THEN 'antes_jul_2026'
         ELSE strftime(j.fecha_registro, '%Y-%m') END        AS cohorte_registro,
    date_diff('day', j.fecha_registro, getvariable('corte')) AS antiguedad_dias,
    (j.fecha_registro >= getvariable('inicio'))              AS historia_completa,  -- la ventana cubre toda su vida
    -- Contacto y controles (solo jugadores presentes en Registros)
    r.estado_cuenta_cod, r.kyc_cod, r.verificacion_celular_cod,
    r.telefono_10, r.telefono_estado, r.jugadores_mismo_telefono,
    date_diff('year', r.fecha_nacimiento, getvariable('corte')::DATE) AS edad_al_corte,
    r.genero, r.region, r.departamento,
    r.depositante_plataforma, r.fecha_primer_deposito_plataforma, r.monto_primer_deposito_plataforma,
    r.promocode_registro, r.agent_id AS agent_id_registro,
    -- Recargas
    coalesce(rc.rec_n, 0) AS rec_n, coalesce(rc.rec_monto, 0) AS rec_monto,
    rc.rec_promedio, rc.rec_mediana, rc.rec_primera_obs, rc.rec_ultima_obs,
    date_diff('day', rc.rec_ultima_obs, getvariable('corte')) AS rec_dias_desde_ultima,
    coalesce(rc.rec_dias_activos, 0) AS rec_dias_activos, rc.rec_intervalo_mediano_dias,
    coalesce(rc.rec_n_v1, 0) AS rec_n_v1, coalesce(rc.rec_n_v2, 0) AS rec_n_v2, coalesce(rc.rec_n_v3, 0) AS rec_n_v3,
    coalesce(rc.rec_monto_v1, 0) AS rec_monto_v1, coalesce(rc.rec_monto_v2, 0) AS rec_monto_v2, coalesce(rc.rec_monto_v3, 0) AS rec_monto_v3,
    coalesce(rc.rec_n_jul, 0) AS rec_n_jul, coalesce(rc.rec_n_ago, 0) AS rec_n_ago, coalesce(rc.rec_n_sep, 0) AS rec_n_sep,
    rc.rec_metodo_principal, rc.rec_franja_principal, rc.rec_pct_madrugada, rc.rec_max_en_un_dia,
    -- Apuestas deportivas
    coalesce(ap.apu_n, 0) AS apu_n, coalesce(ap.apu_monto, 0) AS apu_monto, ap.apu_monto_mediano,
    ap.apu_primera_obs, ap.apu_ultima_obs,
    date_diff('day', ap.apu_ultima_obs, getvariable('corte')) AS apu_dias_desde_ultima,
    coalesce(ap.apu_dias_activos, 0) AS apu_dias_activos, ap.apu_intervalo_mediano_dias,
    coalesce(ap.apu_n_v1, 0) AS apu_n_v1, coalesce(ap.apu_n_v2, 0) AS apu_n_v2, coalesce(ap.apu_n_v3, 0) AS apu_n_v3,
    coalesce(ap.apu_dias_v1, 0) AS apu_dias_v1, coalesce(ap.apu_dias_v2, 0) AS apu_dias_v2, coalesce(ap.apu_dias_v3, 0) AS apu_dias_v3,
    coalesce(ap.apu_n_jul, 0) AS apu_n_jul, coalesce(ap.apu_n_ago, 0) AS apu_n_ago, coalesce(ap.apu_n_sep, 0) AS apu_n_sep,
    ap.apu_pct_en_vivo, ap.apu_pct_prepartido, ap.apu_pct_simple, ap.apu_selecciones_mediana,
    ap.apu_pct_con_bono, ap.apu_pct_cashout, ap.apu_pct_fin_de_semana,
    ap.apu_canal_principal, ap.apu_franja_principal, ap.apu_dia_semana_principal,
    -- Casino
    coalesce(cs.cas_n, 0) AS cas_n, coalesce(cs.cas_monto, 0) AS cas_monto, coalesce(cs.cas_dias_activos, 0) AS cas_dias_activos,
    cs.cas_primera_obs, cs.cas_ultima_obs, cs.cas_proveedor_principal, cs.cas_juego_principal,
    -- Retiros
    coalesce(rt.ret_n, 0) AS ret_n, coalesce(rt.ret_monto_neto, 0) AS ret_monto_neto,
    rt.ret_primera_obs, rt.ret_ultima_obs, rt.ret_minutos_mediana, rt.ret_metodo_principal,
    -- Activación (solo con historia completa: registrados dentro de la ventana)
    CASE WHEN j.fecha_registro >= getvariable('inicio')
         THEN date_diff('hour', j.fecha_registro, rc.rec_primera_obs) END AS horas_registro_a_primera_recarga,
    CASE WHEN j.fecha_registro >= getvariable('inicio')
         THEN date_diff('hour', j.fecha_registro, ap.apu_primera_obs) END AS horas_registro_a_primera_apuesta,
    CASE WHEN j.fecha_registro >= getvariable('inicio')
         THEN date_diff('hour', rc.rec_primera_obs, ap.apu_primera_obs) END AS horas_primera_recarga_a_primera_apuesta,
    -- Evolución: actividad = recarga, apuesta deportiva o ronda de casino en la ventana de 30 días
    (coalesce(rc.rec_n_v1, 0) + coalesce(ap.apu_n_v1, 0) + coalesce(cs.cas_n_v1, 0)) > 0 AS activo_v1,
    (coalesce(rc.rec_n_v2, 0) + coalesce(ap.apu_n_v2, 0) + coalesce(cs.cas_n_v2, 0)) > 0 AS activo_v2,
    (coalesce(rc.rec_n_v3, 0) + coalesce(ap.apu_n_v3, 0) + coalesce(cs.cas_n_v3, 0)) > 0 AS activo_v3,
    -- Ventanas en las que el jugador ya existía (para no confundir "no registrado aún" con "inactivo")
    CASE WHEN j.fecha_registro IS NULL OR j.fecha_registro <= getvariable('corte') - INTERVAL 60 DAY THEN 3
         WHEN j.fecha_registro <= getvariable('corte') - INTERVAL 30 DAY THEN 2
         ELSE 1 END AS ventanas_elegibles,
    greatest(rc.rec_ultima_obs, ap.apu_ultima_obs, cs.cas_ultima_obs) AS ultima_actividad_obs,
    date_diff('day', greatest(rc.rec_ultima_obs, ap.apu_ultima_obs, cs.cas_ultima_obs), getvariable('corte')) AS dias_desde_ultima_actividad
FROM core.jugador j
LEFT JOIN core.registro r USING (player_id)
LEFT JOIN m_rec rc USING (player_id)
LEFT JOIN m_apu ap USING (player_id)
LEFT JOIN m_cas cs USING (player_id)
LEFT JOIN m_ret rt USING (player_id)
-- Solo jugadores que existían al corte: registrados antes del corte o con alguna operación hasta el corte.
-- Así, cargar datos posteriores no cambia la foto de un corte anterior.
WHERE j.fecha_registro <= getvariable('corte')
   OR rc.player_id IS NOT NULL OR ap.player_id IS NOT NULL OR cs.player_id IS NOT NULL OR rt.player_id IS NOT NULL;

-- Patrón de actividad en las 3 ventanas (v3-v2-v1), p. ej. '1-0-1' = retorno.
CREATE OR REPLACE TABLE mart.jugador_resumen AS
SELECT *,
    CASE WHEN ventanas_elegibles = 3 THEN concat(activo_v3::INT, '-', activo_v2::INT, '-', activo_v1::INT)
         WHEN ventanas_elegibles = 2 THEN concat('x-', activo_v2::INT, '-', activo_v1::INT)
         ELSE concat('x-x-', activo_v1::INT) END AS patron_actividad
FROM mart.jugador_resumen;
