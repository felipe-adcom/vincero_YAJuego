-- =====================================================================
-- Audiencias SMS v1. Requiere variables `corte`, `version` y `semilla`.
-- 1) Cada campaña define candidatos con una regla exacta.
-- 2) Filtros comunes: contactable con los datos disponibles y sin señal de
--    revisión de juego responsable.
-- 3) Un jugador recibe como máximo UNA campaña por ola: gana la de mayor
--    prioridad; las demás quedan registradas como suprimidas (trazabilidad).
-- 4) Grupo de control determinístico por hash(player_id, semilla, campaña):
--    la misma corrida siempre produce la misma asignación.
-- Todas las audiencias quedan `pendiente_validacion` hasta cruzar consentimiento
-- de contacto, autoexclusión y bloqueos (no vienen en los archivos recibidos).
-- =====================================================================

CREATE OR REPLACE TABLE mart.campana_catalogo AS
SELECT * FROM (VALUES
  ('ACT01', 1, 'Activación temprana: registro sin recarga (0-7 días)', 'Primera recarga', 20,
   'h_sin_recarga_0_7d'),
  ('ONB02', 2, 'Segunda recarga: una sola recarga y 7+ días sin actividad', 'Segunda recarga', 20,
   'h_una_sola_recarga AND dias_desde_ultima_actividad >= 7'),
  ('XS03', 3, 'Recargó y nunca apostó en deportes (registrados desde julio)', 'Primera apuesta deportiva', 20,
   'h_recarga_sin_apuesta_deportiva AND historia_completa AND rec_dias_desde_ultima <= 60'),
  ('RET04', 4, 'Pre-abandono: atrasado frente a su propio ritmo (8-30 días)', 'Retomar actividad', 20,
   'h_atrasado_vs_ritmo_propio'),
  ('ACT05', 5, 'Recordatorio de activación: registro sin recarga (8-30 días)', 'Primera recarga', 20,
   'h_sin_recarga_8_30d'),
  ('REC06', 6, 'Recuperación: inactivo 31-60 días con actividad previa', 'Retomar actividad', 20,
   'ciclo_vida = ''5_inactivo_31_60''')
) t(campana, prioridad, nombre, objetivo, pct_control, regla_sql);

CREATE OR REPLACE TABLE mart.audiencia_sms_detalle AS
WITH b AS (
    SELECT s.*, j.historia_completa, j.dias_desde_ultima_actividad, j.rec_dias_desde_ultima,
           j.rec_n, j.apu_n, j.antiguedad_dias, j.telefono_10
    FROM mart.segmento_jugador s JOIN mart.jugador_resumen j USING (player_id)
),
candidatos AS (
    SELECT 'ACT01' AS campana, player_id, 'Registrado hace ' || antiguedad_dias || ' días, sin recarga ni apuesta' AS motivo FROM b WHERE h_sin_recarga_0_7d
    UNION ALL SELECT 'ONB02', player_id, '1 recarga; ' || dias_desde_ultima_actividad || ' días sin actividad' FROM b
        WHERE h_una_sola_recarga AND dias_desde_ultima_actividad >= 7
    UNION ALL SELECT 'XS03', player_id, rec_n || ' recargas y 0 apuestas deportivas' FROM b
        WHERE h_recarga_sin_apuesta_deportiva AND historia_completa AND rec_dias_desde_ultima <= 60
    UNION ALL SELECT 'RET04', player_id, dias_desde_ultima_actividad || ' días sin actividad; supera 2x su ritmo habitual' FROM b
        WHERE h_atrasado_vs_ritmo_propio
    UNION ALL SELECT 'ACT05', player_id, 'Registrado hace ' || antiguedad_dias || ' días, sin recarga ni apuesta' FROM b WHERE h_sin_recarga_8_30d
    UNION ALL SELECT 'REC06', player_id, dias_desde_ultima_actividad || ' días sin actividad tras haber jugado' FROM b
        WHERE ciclo_vida = '5_inactivo_31_60'
)
SELECT
    c.campana, k.prioridad, c.player_id, c.motivo AS motivo_inclusion,
    b.ciclo_vida, b.pref_modalidad, b.franja_habitual, b.estado_contacto,
    b.senal_revision_juego_responsable,
    CASE
        WHEN b.estado_contacto <> 'contactable_pendiente_consentimiento' THEN 'excluido_' || b.estado_contacto
        WHEN b.senal_revision_juego_responsable THEN 'excluido_revision_juego_responsable'
        WHEN row_number() OVER (PARTITION BY c.player_id, (b.estado_contacto = 'contactable_pendiente_consentimiento'
                                    AND NOT b.senal_revision_juego_responsable) ORDER BY k.prioridad) > 1
             THEN 'suprimido_por_prioridad'
        ELSE 'seleccionado' END AS resultado,
    CASE WHEN (hash(c.player_id || getvariable('semilla') || c.campana) % 100) < k.pct_control
         THEN 'control' ELSE 'envio' END AS grupo,
    CASE WHEN c.campana IN ('RET04', 'REC06') AND b.pref_modalidad IN ('en_vivo', 'prepartido')
         THEN b.pref_modalidad ELSE 'general' END AS variante_copy,
    getvariable('corte')::TIMESTAMP AS fecha_corte,
    getvariable('version') AS version_reglas
FROM candidatos c
JOIN mart.campana_catalogo k USING (campana)
JOIN b USING (player_id);

-- Audiencia operativa: solo seleccionados, con lo mínimo para activar y controlar.
CREATE OR REPLACE TABLE mart.audiencia_sms AS
SELECT d.campana, d.player_id, j.telefono_10 AS telefono, d.grupo, d.variante_copy,
       d.franja_habitual,
       -- Ventana de envío dentro del horario permitido para mensajes comerciales
       -- (Ley 2300 de 2023: lun-vie 7:00-19:00, sáb 8:00-15:00, sin domingos ni festivos).
       CASE d.franja_habitual WHEN 'manana' THEN 'lun-vie 09:00-11:00 / sáb 09:00-11:00'
                              WHEN 'tarde'  THEN 'lun-vie 12:00-15:00 / sáb 12:00-15:00'
                              WHEN 'noche'  THEN 'lun-vie 17:00-19:00 / sáb 13:00-15:00'
                              ELSE 'lun-vie 09:00-11:00' END AS ventana_envio_sugerida,
       d.motivo_inclusion, d.fecha_corte, d.version_reglas,
       'pendiente_validacion_consentimiento_autoexclusion' AS estado_activacion
FROM mart.audiencia_sms_detalle d JOIN mart.jugador_resumen j USING (player_id)
WHERE d.resultado = 'seleccionado';
