-- =====================================================================
-- Capa CORE: datos limpios y tipados, una fila por unidad real de cada fuente.
-- Se reconstruye completa en cada ejecución a partir de staging (idempotente).
-- Solo usa cargas activas (estado = 'cargado'); los archivos reemplazados o
-- duplicados quedan en staging para auditoría pero no alimentan esta capa.
-- Si un mismo identificador aparece en varias cargas activas, gana la más reciente.
-- Test vacío = no es prueba: las vistas de lista del back office lo exportan vacío.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS core;

-- Fuentes que pueden no haber llegado aún: la tabla de staging existe vacía.
CREATE TABLE IF NOT EXISTS stg.casino (_load_id INTEGER, _archivo VARCHAR, _sha256 VARCHAR, _fila INTEGER,
    bet_id VARCHAR, client_id VARCHAR, provider VARCHAR, game VARCHAR, stake VARCHAR, win VARCHAR, status VARCHAR,
    placed_date VARCHAR, last_edit VARCHAR, settled_date VARCHAR, provider_bet_id VARCHAR, test VARCHAR, bonus VARCHAR);

CREATE OR REPLACE TEMP VIEW cargas_activas AS
SELECT load_id FROM meta.manifiesto WHERE estado = 'cargado';

-- ---------------------------------------------------------------------
-- Registros: snapshot de atributos del jugador al momento de exportar.
-- Una fila por jugador. Se excluyen nombre, dirección, documento e IP:
-- no son necesarios para analítica ni campañas (minimización de datos).
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE core.registro AS
WITH base AS (
    SELECT *, row_number() OVER (PARTITION BY id ORDER BY _load_id DESC, _fila) AS rn
    FROM stg.registros WHERE _load_id IN (SELECT load_id FROM cargas_activas)
), tel AS (
    SELECT *, regexp_replace(coalesce(mobilephone, ''), '[^0-9]', '', 'g') AS tel_digitos FROM base WHERE rn = 1
)
SELECT
    id                                              AS player_id,
    TRY_CAST(insert_date AS TIMESTAMP)              AS fecha_registro,
    -- Hasta septiembre el estado llega como código (1, -2, ...); desde octubre como texto (Active, Suspended).
    CASE WHEN status = 'Active' THEN 1 ELSE TRY_CAST(status AS INTEGER) END AS estado_cuenta_cod,
    status                                          AS estado_cuenta_txt,
    TRY_CAST(kyc AS INTEGER)                        AS kyc_cod,
    TRY_CAST(kyc_doc_status AS INTEGER)             AS kyc_doc_cod,
    TRY_CAST(mobile_verification AS INTEGER)        AS verificacion_celular_cod,
    TRY_CAST(mobile_verification_date AS TIMESTAMP) AS fecha_verificacion_celular,
    TRY_CAST(registration_source AS INTEGER)        AS fuente_registro_cod,
    agent_id, network_id,
    promocode                                       AS promocode_registro,
    btag,
    TRY_CAST(vip AS INTEGER)                        AS vip,
    coalesce(TRY_CAST(test AS INTEGER), 0)          AS es_prueba,
    TRY_CAST(depositor AS INTEGER)                  AS depositante_plataforma,
    TRY_CAST(first_dep_date AS TIMESTAMP)           AS fecha_primer_deposito_plataforma,
    TRY_CAST(first_dep_amount AS DECIMAL(18,2))     AS monto_primer_deposito_plataforma,
    TRY_CAST(balance AS DECIMAL(18,2))              AS saldo_al_exportar,
    TRY_CAST(last_login AS TIMESTAMP)               AS ultimo_login_al_exportar,
    TRY_CAST(failed_login_attempts AS INTEGER)      AS intentos_login_fallidos,
    TRY_CAST(dob AS DATE)                           AS fecha_nacimiento,
    gender                                          AS genero,
    nationality                                     AS nacionalidad,
    res_region                                      AS region,
    res_department                                  AS departamento,
    res_city                                        AS ciudad,
    TRY_CAST(document_type AS INTEGER)              AS tipo_documento_cod,
    md5(lower(trim(document_id)))                   AS documento_hash,   -- solo para detectar duplicados
    lower(trim(email))                              AS email,
    mobilephone                                     AS telefono_original,
    CASE WHEN length(tel_digitos) = 10 AND tel_digitos LIKE '3%' THEN tel_digitos
         WHEN length(tel_digitos) = 12 AND tel_digitos LIKE '573%' THEN substr(tel_digitos, 3)
    END                                             AS telefono_10,
    CASE WHEN length(tel_digitos) = 10 AND tel_digitos LIKE '3%' THEN 'valido'
         WHEN length(tel_digitos) = 12 AND tel_digitos LIKE '573%' THEN 'valido_con_prefijo_57'
         WHEN tel_digitos = '' THEN 'vacio'
         ELSE 'invalido_o_incompleto' END           AS telefono_estado,
    TRY_CAST(update_date AS TIMESTAMP)              AS fecha_actualizacion_registro,
    update_user                                     AS usuario_actualizacion_registro,
    _archivo AS origen_archivo, _load_id AS origen_load_id
FROM tel;

-- Conflictos de contacto: un teléfono o correo compartido por varios player_id.
CREATE OR REPLACE TABLE core.registro AS
SELECT r.*,
       CASE WHEN telefono_10 IS NOT NULL THEN count(*) OVER (PARTITION BY telefono_10) END AS jugadores_mismo_telefono,
       CASE WHEN email IS NOT NULL THEN count(*) OVER (PARTITION BY email) END             AS jugadores_mismo_email,
       CASE WHEN documento_hash IS NOT NULL THEN count(*) OVER (PARTITION BY documento_hash) END AS jugadores_mismo_documento
FROM core.registro r;

-- ---------------------------------------------------------------------
-- Recargas: una fila por operación acreditada.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE core.recarga AS
SELECT
    id                                    AS recarga_id,
    client_id                             AS player_id,
    TRY_CAST(insert_date AS TIMESTAMP)    AS fecha_hora,
    TRY_CAST(amount AS DECIMAL(18,2))     AS monto,
    TRY_CAST(charge AS DECIMAL(18,2))     AS cargo,
    method                                AS metodo,
    status                                AS estado,
    agent_id, network_id,
    promocode,
    TRY_CAST(manual AS INTEGER)           AS es_manual,
    coalesce(TRY_CAST(test AS INTEGER), 0) AS es_prueba,
    _archivo AS origen_archivo, _load_id AS origen_load_id, _fila AS origen_fila
FROM (SELECT *, row_number() OVER (PARTITION BY id ORDER BY _load_id DESC, _fila) rn
      FROM stg.recargas WHERE _load_id IN (SELECT load_id FROM cargas_activas))
WHERE rn = 1;

-- ---------------------------------------------------------------------
-- Retiros: una fila por solicitud de retiro (el export trae solo PROCESSED).
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE core.retiro AS
SELECT
    id                                          AS retiro_id,
    client_id                                   AS player_id,
    TRY_CAST(insert_date AS TIMESTAMP)          AS fecha_solicitud,
    TRY_CAST(last_update AS TIMESTAMP)          AS fecha_ultima_actualizacion,
    date_diff('minute', TRY_CAST(insert_date AS TIMESTAMP), TRY_CAST(last_update AS TIMESTAMP)) AS minutos_hasta_actualizacion,
    status                                      AS estado,
    method                                      AS metodo,
    TRY_CAST(requested_amount AS DECIMAL(18,2)) AS monto_solicitado,
    TRY_CAST(net_amount AS DECIMAL(18,2))       AS monto_neto,
    TRY_CAST(tax AS DECIMAL(18,2))              AS impuesto,
    TRY_CAST(deposit_fee AS DECIMAL(18,2))      AS comision,
    profile                                     AS perfil_retiro,
    TRY_CAST(risk_level AS INTEGER)             AS nivel_riesgo_cod,
    last_operator                               AS ultimo_operador,
    TRY_CAST(is_manual AS INTEGER)              AS es_manual,
    coalesce(TRY_CAST(test AS INTEGER), 0)      AS es_prueba,
    TRY_CAST(registration_date AS TIMESTAMP)    AS fecha_registro_reportada,
    agent_id, network_id, promocode,
    _archivo AS origen_archivo, _load_id AS origen_load_id, _fila AS origen_fila
FROM (SELECT *, row_number() OVER (PARTITION BY id ORDER BY _load_id DESC, _fila) rn
      FROM stg.retiros WHERE _load_id IN (SELECT load_id FROM cargas_activas))
WHERE rn = 1;

-- ---------------------------------------------------------------------
-- Apuestas deportivas, nivel línea: una fila por (bet_id, bet_type).
-- Las apuestas SYSTEM traen una fila por tamaño de combinación; SubBet ID
-- llega en notación científica desde el origen (precisión perdida) y no sirve
-- como llave, por eso la llave es bet_id + bet_type.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE core.apuesta_linea AS
SELECT
    bet_id, bet_type                            AS tipo_linea,
    client_id                                   AS player_id,
    TRY_CAST(insert_date AS TIMESTAMP)          AS fecha_hora,
    TRY_CAST(settled_date AS TIMESTAMP)         AS fecha_liquidacion,
    TRY_CAST(paid_date AS TIMESTAMP)            AS fecha_pago,
    TRY_CAST(update_date AS TIMESTAMP)          AS fecha_actualizacion,
    status                                      AS estado,
    void_reason                                 AS motivo_anulacion,
    TRY_CAST(stake AS DECIMAL(18,2))            AS monto_apostado,
    TRY_CAST(win AS DECIMAL(18,2))              AS monto_ganado,
    TRY_CAST(pot_win AS DECIMAL(18,2))          AS ganancia_potencial,
    TRY_CAST(total_odd AS DOUBLE)               AS cuota_total,
    split_part(bet_type, ' ', 1)                AS tipo_apuesta,
    TRY_CAST(numlines AS INTEGER)               AS selecciones,
    TRY_CAST(live AS INTEGER)                   AS live_cod,
    source                                      AS canal,
    TRY_CAST(bonus_funds AS INTEGER)            AS con_fondos_bono,
    bonus_id,
    TRY_CAST(cashout AS INTEGER)                AS cashout,
    coalesce(TRY_CAST(test AS INTEGER), 0)      AS es_prueba,
    agent AS agent_id, network AS network_id,
    _archivo AS origen_archivo, _load_id AS origen_load_id, _fila AS origen_fila
FROM (SELECT *, row_number() OVER (PARTITION BY bet_id, bet_type ORDER BY _load_id DESC, _fila) rn
      FROM stg.apuestas WHERE _load_id IN (SELECT load_id FROM cargas_activas))
WHERE rn = 1;

-- Apuestas deportivas, nivel ticket: una fila por bet_id (unidad para contar apuestas).
CREATE OR REPLACE TABLE core.apuesta AS
SELECT
    bet_id, any_value(player_id) AS player_id,
    min(fecha_hora)              AS fecha_hora,
    max(fecha_liquidacion)       AS fecha_liquidacion,
    any_value(tipo_apuesta)      AS tipo_apuesta,
    max(selecciones)             AS selecciones,
    count(*)                     AS lineas,
    sum(monto_apostado)          AS monto_apostado,
    sum(monto_ganado)            AS monto_ganado,
    any_value(live_cod)          AS live_cod,
    any_value(canal)             AS canal,
    max(con_fondos_bono)         AS con_fondos_bono,
    max(cashout)                 AS cashout,
    CASE WHEN bool_or(estado IN ('Running', 'Reopen')) THEN 'abierta'
         WHEN bool_and(estado IN ('Void', 'Refund', 'Reopen Refund')) THEN 'anulada_o_reembolsada'
         ELSE 'liquidada' END    AS estado_ticket,
    max(es_prueba)               AS es_prueba
FROM core.apuesta_linea
GROUP BY bet_id;

-- ---------------------------------------------------------------------
-- Casino: una fila por ronda (Bet Id). Test llega vacío en la mayoría de filas: vacío = no es prueba.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE core.casino AS
SELECT
    bet_id                                    AS ronda_id,
    client_id                                 AS player_id,
    TRY_CAST(placed_date AS TIMESTAMP)        AS fecha_hora,
    TRY_CAST(settled_date AS TIMESTAMP)       AS fecha_liquidacion,
    provider                                  AS proveedor,
    game                                      AS juego,
    TRY_CAST(stake AS DECIMAL(18,2))          AS monto_apostado,
    TRY_CAST(win AS DECIMAL(18,2))            AS monto_ganado,
    status                                    AS estado,
    coalesce(TRY_CAST(bonus AS INTEGER), 0)   AS con_bono,
    coalesce(TRY_CAST(test AS INTEGER), 0)    AS es_prueba,
    _archivo AS origen_archivo, _load_id AS origen_load_id, _fila AS origen_fila
FROM (SELECT *, row_number() OVER (PARTITION BY bet_id ORDER BY _load_id DESC, _fila) rn
      FROM stg.casino WHERE _load_id IN (SELECT load_id FROM cargas_activas))
WHERE rn = 1;

-- ---------------------------------------------------------------------
-- Universo de jugadores: todo player_id visto en cualquier fuente.
-- La fecha de registro sale de Registros; si no está, de Retiros (que la
-- reporta); si no aparece en ninguna, queda desconocida (NULL), no se inventa.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE core.jugador AS
WITH ids AS (
    SELECT player_id FROM core.registro
    UNION SELECT player_id FROM core.recarga
    UNION SELECT player_id FROM core.retiro
    UNION SELECT player_id FROM core.apuesta
    UNION SELECT player_id FROM core.casino
), reg_ret AS (
    SELECT player_id, min(fecha_registro_reportada) AS fecha_registro_reportada FROM core.retiro GROUP BY 1
)
SELECT
    i.player_id,
    r.player_id IS NOT NULL                                 AS en_registros,
    i.player_id IN (SELECT player_id FROM core.recarga)     AS en_recargas,
    i.player_id IN (SELECT player_id FROM core.retiro)      AS en_retiros,
    i.player_id IN (SELECT player_id FROM core.apuesta)     AS en_apuestas,
    i.player_id IN (SELECT player_id FROM core.casino)      AS en_casino,
    coalesce(r.fecha_registro, rr.fecha_registro_reportada) AS fecha_registro,
    CASE WHEN r.fecha_registro IS NOT NULL THEN 'registros'
         WHEN rr.fecha_registro_reportada IS NOT NULL THEN 'retiros'
         ELSE 'desconocida' END                             AS fuente_fecha_registro
FROM ids i
LEFT JOIN core.registro r USING (player_id)
LEFT JOIN reg_ret rr USING (player_id);
