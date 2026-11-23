-- =====================================================================
-- Segmentación v1: etiquetas por jugador al corte.
-- Requiere variables `corte` y `version`.
-- * ciclo_vida: segmento amplio, excluyente (una sola etiqueta por jugador).
-- * hipersegmentos: etiquetas que pueden superponerse; la selección de campañas
--   (40_audiencias.sql) resuelve los choques por prioridad.
-- Los umbrales salen de la distribución observada y quedan guardados en
-- mart.parametros_segmentacion para que cada corrida sea auditable.
-- =====================================================================

-- ---------- Umbrales derivados de los datos ----------
CREATE OR REPLACE TABLE mart.parametros_segmentacion AS
WITH rec AS (SELECT * FROM mart.jugador_resumen WHERE rec_n > 0)
SELECT getvariable('version') AS version_reglas, getvariable('corte')::TIMESTAMP AS fecha_corte, * FROM (
    SELECT 'rec_max_dia_p99' AS parametro, quantile_disc(rec_max_en_un_dia, 0.99)::DOUBLE AS valor,
           'Recargas en un mismo día: percentil 99 entre jugadores con recarga' AS descripcion FROM rec
    UNION ALL SELECT 'rec_monto_v1_p90', quantile_disc(rec_monto_v1, 0.90)::DOUBLE,
           'Monto recargado en últimos 30 días: percentil 90 (jugadores con recarga)' FROM rec
    UNION ALL SELECT 'valor_p50', quantile_disc(rec_monto, 0.50)::DOUBLE, 'Monto recargado en la ventana: mediana' FROM rec
    UNION ALL SELECT 'valor_p90', quantile_disc(rec_monto, 0.90)::DOUBLE, 'Monto recargado en la ventana: percentil 90' FROM rec
    UNION ALL SELECT 'dias_activo_max', 14, 'Días sin actividad tolerados como "activo" (≈p85 del intervalo entre días de apuesta)'
    UNION ALL SELECT 'dias_enfriando_max', 30, 'Límite superior de "enfriándose"; más allá es inactivo'
    UNION ALL SELECT 'min_tickets_preferencia', 5, 'Mínimo de apuestas para asignar preferencia deportiva'
);

CREATE OR REPLACE TEMP MACRO p(nombre) AS (SELECT valor FROM mart.parametros_segmentacion WHERE parametro = nombre);

CREATE OR REPLACE TABLE mart.segmento_jugador AS
WITH b AS (
    SELECT j.*,
        least(rec_primera_obs, apu_primera_obs) AS primera_actividad_obs,
        coalesce(apu_intervalo_mediano_dias, rec_intervalo_mediano_dias) AS intervalo_propio_dias
    FROM mart.jugador_resumen j
)
SELECT
    player_id,
    getvariable('corte')::TIMESTAMP AS fecha_corte,
    getvariable('version')          AS version_reglas,
    current_timestamp::TIMESTAMP    AS calculado_en,

    -- ---------- Segmento amplio de ciclo de vida (excluyente, en orden de prioridad) ----------
    CASE
        WHEN historia_completa AND rec_n = 0 AND apu_n = 0 AND cas_n = 0 THEN '1_nuevo_sin_actividad'
        WHEN historia_completa AND primera_actividad_obs > getvariable('corte') - INTERVAL 30 DAY THEN '2_nuevo_en_activacion'
        WHEN dias_desde_ultima_actividad <= p('dias_activo_max')                    THEN '3_activo'
        WHEN dias_desde_ultima_actividad <= p('dias_enfriando_max')                 THEN '4_enfriandose'
        WHEN dias_desde_ultima_actividad <= 60                                      THEN '5_inactivo_31_60'
        WHEN dias_desde_ultima_actividad IS NOT NULL                                THEN '6_inactivo_61_mas'
        ELSE '7_sin_actividad_de_juego_observada'
    END AS ciclo_vida,

    -- ---------- Nivel de valor (solo informativo; no se usa para presionar más recargas) ----------
    CASE WHEN rec_n = 0 THEN 'sin_recarga'
         WHEN rec_monto >= p('valor_p90') THEN 'alto'
         WHEN rec_monto >= p('valor_p50') THEN 'medio'
         ELSE 'bajo' END AS nivel_valor,

    -- ---------- Hipersegmentos (etiquetas superponibles) ----------
    (historia_completa AND rec_n = 0 AND apu_n = 0 AND cas_n = 0 AND coalesce(depositante_plataforma, 0) = 0
        AND antiguedad_dias <= 7)                                   AS h_sin_recarga_0_7d,
    (historia_completa AND rec_n = 0 AND apu_n = 0 AND cas_n = 0 AND coalesce(depositante_plataforma, 0) = 0
        AND antiguedad_dias BETWEEN 8 AND 30)                       AS h_sin_recarga_8_30d,
    (historia_completa AND rec_n = 0 AND apu_n = 0 AND cas_n = 0 AND coalesce(depositante_plataforma, 0) = 0
        AND antiguedad_dias > 30)                                   AS h_sin_recarga_31d_mas,
    (historia_completa AND rec_n = 0 AND coalesce(depositante_plataforma, 0) = 1)
                                                                    AS h_deposito_posterior_al_corte,
    (rec_n > 0 AND apu_n = 0)                                       AS h_recarga_sin_apuesta_deportiva,
    (historia_completa AND rec_n = 1
        AND rec_primera_obs <= getvariable('corte') - INTERVAL 7 DAY) AS h_una_sola_recarga,
    (greatest(apu_dias_activos, rec_dias_activos) >= 3
        AND dias_desde_ultima_actividad BETWEEN 8 AND 30
        AND dias_desde_ultima_actividad > 2 * greatest(intervalo_propio_dias, 3)) AS h_atrasado_vs_ritmo_propio,
    (apu_dias_v1 > 0 AND (apu_dias_v2 + apu_dias_v3) / 2.0 >= 4
        AND apu_dias_v1 <= 0.5 * (apu_dias_v2 + apu_dias_v3) / 2.0) AS h_caida_de_frecuencia,
    (patron_actividad IN ('1-0-1', 'x-0-1'))                        AS h_retorno,
    (patron_actividad = '1-1-1')                                    AS h_continuo_3_ventanas,

    -- ---------- Preferencias deportivas observadas (requiere mínimo de apuestas) ----------
    CASE WHEN apu_n < p('min_tickets_preferencia') THEN 'insuficiente'
         WHEN apu_pct_en_vivo >= 0.6 THEN 'en_vivo'
         WHEN apu_pct_prepartido >= 0.6 THEN 'prepartido'
         ELSE 'mixto' END AS pref_modalidad,
    CASE WHEN apu_n < p('min_tickets_preferencia') THEN 'insuficiente'
         WHEN apu_pct_simple >= 0.7 THEN 'simples'
         WHEN apu_pct_simple <= 0.3 THEN 'combinadas'
         ELSE 'mixto' END AS pref_tipo_apuesta,
    CASE WHEN apu_n < p('min_tickets_preferencia') THEN NULL
         ELSE apu_pct_fin_de_semana >= 0.5 END AS pref_fin_de_semana,
    -- Franja horaria habitual: de apuestas, si no de recargas, si no la hora del registro.
    coalesce(apu_franja_principal, rec_franja_principal,
             CASE WHEN hour(fecha_registro) < 6 THEN 'madrugada' WHEN hour(fecha_registro) < 12 THEN 'manana'
                  WHEN hour(fecha_registro) < 18 THEN 'tarde' ELSE 'noche' END) AS franja_habitual,

    -- ---------- Protección: señales que excluyen de comunicaciones promocionales ----------
    (coalesce(rec_max_en_un_dia, 0) >= p('rec_max_dia_p99')
     OR (rec_n >= 5 AND rec_pct_madrugada >= 0.5)
     OR (rec_monto_v1 >= p('rec_monto_v1_p90') AND rec_monto_v1 >= 3 * (rec_monto_v2 + rec_monto_v3) / 2.0)
    ) AS senal_revision_juego_responsable,

    -- ---------- Contactabilidad SMS con la información disponible ----------
    CASE WHEN NOT en_registros                       THEN 'sin_datos_de_contacto'
         WHEN coalesce(estado_cuenta_cod, 0) <> 1    THEN 'cuenta_no_activa'
         WHEN telefono_10 IS NULL                    THEN 'telefono_invalido'
         WHEN jugadores_mismo_telefono > 1           THEN 'telefono_compartido'
         WHEN edad_al_corte IS NULL OR edad_al_corte < 18 THEN 'edad_no_verificada'
         ELSE 'contactable_pendiente_consentimiento' END AS estado_contacto
FROM b;
