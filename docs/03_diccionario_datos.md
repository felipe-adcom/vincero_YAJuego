# Diccionario de datos

Generado con `python pipeline/diccionario.py` a partir de la base: los tipos son los reales.
Las tablas `stg.*` conservan las columnas originales en texto (`snake_case` del encabezado) más
`_load_id`, `_archivo`, `_sha256` y `_fila`. Versión CSV: `reports/diccionario_datos.csv`.

## `core.registro`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `player_id` | VARCHAR | Identificador del jugador | Registros.ID | Texto |
| `fecha_registro` | TIMESTAMP | Fecha y hora de creación de la cuenta | Registros.Insert Date |  |
| `estado_cuenta_cod` | INTEGER | Código de estado de la cuenta (1 = activa; negativos a validar) | Registros.Status | Active se normaliza a 1 |
| `estado_cuenta_txt` | VARCHAR | Estado de cuenta tal como llega (código hasta sep; texto Active/Suspended desde oct) | Registros.Status |  |
| `kyc_cod` | INTEGER | Código KYC (significado a validar) | Registros.Kyc |  |
| `kyc_doc_cod` | INTEGER | Estado de documentos KYC (a validar) | Registros.Kyc Doc Status |  |
| `verificacion_celular_cod` | INTEGER | Verificación del celular: 30 verificado, 20 no verificado | Registros.Mobile Verification |  |
| `fecha_verificacion_celular` | TIMESTAMP | Fecha de verificación del celular | Registros.Mobile Verification Date |  |
| `fuente_registro_cod` | INTEGER | Código de fuente de registro (12/13, a validar) | Registros.Registration Source |  |
| `agent_id` | VARCHAR | Agente | Agent ID |  |
| `network_id` | VARCHAR | Red | Network ID |  |
| `promocode_registro` | VARCHAR | Código promocional/afiliado de registro | Registros.Promocode |  |
| `btag` | VARCHAR | Etiqueta de afiliación | Registros.BTAG |  |
| `vip` | INTEGER | Marca VIP | Registros.Vip |  |
| `es_prueba` | INTEGER | Registro de prueba (vacío = no) | Test |  |
| `depositante_plataforma` | INTEGER | La plataforma lo marca como depositante a la fecha de exportación | Registros.Depositor |  |
| `fecha_primer_deposito_plataforma` | TIMESTAMP | Primer depósito histórico según la plataforma | Registros.First Dep. Date | Puede ser posterior al corte |
| `monto_primer_deposito_plataforma` | DECIMAL(18,2) | Monto del primer depósito histórico (COP) | Registros.First Dep. Amount |  |
| `saldo_al_exportar` | DECIMAL(18,2) | Saldo a la fecha de exportación, no al corte | Registros.Balance | No usar para segmentar |
| `ultimo_login_al_exportar` | TIMESTAMP | Último login a la fecha de exportación | Registros.Last Login |  |
| `intentos_login_fallidos` | INTEGER | Intentos fallidos de login | Registros.Failed Login Attempts |  |
| `fecha_nacimiento` | DATE | Fecha de nacimiento | Registros.Dob |  |
| `genero` | VARCHAR | Género declarado | Registros.Gender |  |
| `nacionalidad` | VARCHAR | Nacionalidad | Registros.Nationality |  |
| `region` | VARCHAR | Región de residencia | Registros.Res Region |  |
| `departamento` | VARCHAR | Departamento de residencia | Registros.Res Department |  |
| `ciudad` | VARCHAR | Ciudad de residencia | Registros.Res City |  |
| `tipo_documento_cod` | INTEGER | Tipo de documento (código) | Registros.Document Type |  |
| `documento_hash` | VARCHAR | Huella del documento, solo para detectar cuentas duplicadas | Registros.Document Id | md5(lower(trim(Document Id))) |
| `email` | VARCHAR | Correo en minúsculas | Registros.Email | lower(trim(Email)) |
| `telefono_original` | VARCHAR | Teléfono tal como llegó | Registros.Mobilephone |  |
| `telefono_10` | VARCHAR | Celular normalizado a 10 dígitos | Registros.Mobilephone | Solo dígitos; 10 que inician en 3, o 12 que inician en 573 sin el 57; si no, NULL |
| `telefono_estado` | VARCHAR | Resultado de la normalización | Derivado | valido / valido_con_prefijo_57 / invalido_o_incompleto / vacio |
| `fecha_actualizacion_registro` | TIMESTAMP | Última actualización del registro | Registros.Update Date |  |
| `usuario_actualizacion_registro` | VARCHAR | Usuario u operador que actualizó | Registros.Update User |  |
| `origen_archivo` | VARCHAR | Archivo del que proviene la fila | Manifiesto |  |
| `origen_load_id` | INTEGER | Carga del manifiesto | Manifiesto |  |
| `jugadores_mismo_telefono` | BIGINT | Cuántos player_id comparten el teléfono | Derivado | count(*) over (partition by telefono_10) |
| `jugadores_mismo_email` | BIGINT | Cuántos player_id comparten el correo | Derivado | count(*) over (partition by email) |
| `jugadores_mismo_documento` | BIGINT | Cuántos player_id comparten documento | Derivado | count(*) over (partition by documento_hash) |

## `core.recarga`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `recarga_id` | VARCHAR | Identificador de la recarga | Recargas.Id |  |
| `player_id` | VARCHAR | Jugador | Recargas.Client ID |  |
| `fecha_hora` | TIMESTAMP | Fecha y hora de la recarga (hora local supuesta) | Recargas.Insert Date |  |
| `monto` | DECIMAL(18,2) | Monto acreditado (COP) | Recargas.Amount |  |
| `cargo` | DECIMAL(18,2) | Cargo cobrado | Recargas.Charge |  |
| `metodo` | VARCHAR | Medio de pago | Recargas.Method |  |
| `estado` | VARCHAR | Estado de la operación | Recargas.Status | Solo CREDITED en los exports |
| `agent_id` | VARCHAR | Agente | Agent ID |  |
| `network_id` | VARCHAR | Red | Network ID |  |
| `promocode` | VARCHAR | Código promocional | Promocode |  |
| `es_manual` | INTEGER | Recarga manual | Recargas.Manual |  |
| `es_prueba` | INTEGER | Registro de prueba (vacío = no) | Test |  |
| `origen_archivo` | VARCHAR | Archivo del que proviene la fila | Manifiesto |  |
| `origen_load_id` | INTEGER | Carga del manifiesto | Manifiesto |  |
| `origen_fila` | INTEGER | Fila del Excel (1 = encabezado) | Manifiesto |  |

## `core.retiro`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `retiro_id` | VARCHAR | Identificador del retiro | Retiros.Id |  |
| `player_id` | VARCHAR | Jugador | Retiros.Client ID |  |
| `fecha_solicitud` | TIMESTAMP | Fecha de la solicitud | Retiros.Insert Date |  |
| `fecha_ultima_actualizacion` | TIMESTAMP | Fecha de procesamiento; define el periodo del archivo | Retiros.Last Update |  |
| `minutos_hasta_actualizacion` | BIGINT | Tiempo de procesamiento observado | Derivado | Last Update - Insert Date (minutos) |
| `estado` | VARCHAR | Estado | Retiros.Status | Solo PROCESSED en los exports |
| `metodo` | VARCHAR | Medio de pago del retiro | Retiros.Method |  |
| `monto_solicitado` | DECIMAL(18,2) | Monto solicitado (COP) | Retiros.Requested Amount |  |
| `monto_neto` | DECIMAL(18,2) | Monto neto pagado (COP) | Retiros.Net Amount | Solicitado - impuesto |
| `impuesto` | DECIMAL(18,2) | Retención aplicada | Retiros.Tax |  |
| `comision` | DECIMAL(18,2) | Comisión | Retiros.Deposit Fee |  |
| `perfil_retiro` | VARCHAR | Perfil/grupo del jugador al retirar (a validar) | Retiros.Profile |  |
| `nivel_riesgo_cod` | INTEGER | Nivel de riesgo (a validar) | Retiros.Risk Level |  |
| `ultimo_operador` | VARCHAR | Último operador | Retiros.Last Operator |  |
| `es_manual` | INTEGER | Retiro manual | Retiros.Is Manual |  |
| `es_prueba` | INTEGER | Registro de prueba (vacío = no) | Test |  |
| `fecha_registro_reportada` | TIMESTAMP | Fecha de registro del jugador según Retiros | Retiros.Registration Date |  |
| `agent_id` | VARCHAR | Agente | Agent ID |  |
| `network_id` | VARCHAR | Red | Network ID |  |
| `promocode` | VARCHAR | Código promocional | Promocode |  |
| `origen_archivo` | VARCHAR | Archivo del que proviene la fila | Manifiesto |  |
| `origen_load_id` | INTEGER | Carga del manifiesto | Manifiesto |  |
| `origen_fila` | INTEGER | Fila del Excel (1 = encabezado) | Manifiesto |  |

## `core.apuesta_linea`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `bet_id` | VARCHAR | Identificador de la apuesta (ticket) | Apuestas deportivas.Bet ID |  |
| `tipo_linea` | VARCHAR | Tipo de línea (SINGLE 1, MULTIPLE n, COMB n, SYSTEM n) | Apuestas deportivas.Bet Type | Llave: bet_id + tipo_linea |
| `player_id` | VARCHAR | Identificador del jugador (texto) | ID / Client ID |  |
| `fecha_hora` | TIMESTAMP | Fecha y hora de colocación | Apuestas deportivas.Insert Date |  |
| `fecha_liquidacion` | TIMESTAMP | Fecha de liquidación | Apuestas deportivas.Settled Date |  |
| `fecha_pago` | TIMESTAMP | Fecha de pago | Apuestas deportivas.Paid Date |  |
| `fecha_actualizacion` | TIMESTAMP | Última actualización | Apuestas deportivas.Update Date |  |
| `estado` | VARCHAR | Estado de la línea (Win, Lose, Refund, Void, Running, Reopen…) | Apuestas deportivas.Status |  |
| `motivo_anulacion` | VARCHAR | Motivo de anulación | Apuestas deportivas.Void Reason |  |
| `monto_apostado` | DECIMAL(18,2) | Monto apostado en la línea (COP) | Apuestas deportivas.Stake |  |
| `monto_ganado` | DECIMAL(18,2) | Monto pagado al jugador (COP) | Apuestas deportivas.Win |  |
| `ganancia_potencial` | DECIMAL(18,2) | Ganancia potencial | Apuestas deportivas.Pot Win |  |
| `cuota_total` | DOUBLE | Cuota total | Apuestas deportivas.Total Odd |  |
| `tipo_apuesta` | VARCHAR | SINGLE, MULTIPLE, COMB o SYSTEM | Apuestas deportivas.Bet Type | Primera palabra de Bet Type |
| `selecciones` | INTEGER | Número de selecciones | Apuestas deportivas.Numlines |  |
| `live_cod` | INTEGER | 0 prepartido, 1 en vivo, 2 mixta (a validar) | Apuestas deportivas.Live |  |
| `canal` | VARCHAR | Canal (Mobile, Web, apk23, apk25) | Apuestas deportivas.Source |  |
| `con_fondos_bono` | INTEGER | Apuesta hecha con fondos de bono | Apuestas deportivas.Bonus Funds |  |
| `bonus_id` | VARCHAR | Bono usado | Apuestas deportivas.Bonus Id |  |
| `cashout` | INTEGER | Usó cashout | Apuestas deportivas.Cashout |  |
| `es_prueba` | INTEGER | Registro de prueba (vacío = no) | Test |  |
| `agent_id` | VARCHAR | Agente | Agent ID |  |
| `network_id` | VARCHAR | Red | Network ID |  |
| `origen_archivo` | VARCHAR | Archivo del que proviene la fila | Manifiesto |  |
| `origen_load_id` | INTEGER | Carga del manifiesto | Manifiesto |  |
| `origen_fila` | INTEGER | Fila del Excel (1 = encabezado) | Manifiesto |  |

## `core.apuesta`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `bet_id` | VARCHAR | Identificador de la apuesta (ticket) | Apuestas deportivas.Bet ID |  |
| `player_id` | VARCHAR | Identificador del jugador (texto) | ID / Client ID |  |
| `fecha_hora` | TIMESTAMP | Fecha y hora de la operación | Origen |  |
| `fecha_liquidacion` | TIMESTAMP | Fecha de liquidación | Apuestas deportivas.Settled Date |  |
| `tipo_apuesta` | VARCHAR | SINGLE, MULTIPLE, COMB o SYSTEM | Apuestas deportivas.Bet Type | Primera palabra de Bet Type |
| `selecciones` | INTEGER | Número de selecciones | Apuestas deportivas.Numlines |  |
| `lineas` | BIGINT | Líneas del ticket (SYSTEM tiene varias) | Derivado | count(*) por bet_id |
| `monto_apostado` | DECIMAL(38,2) | Monto total del ticket | Derivado | sum(Stake) de sus líneas |
| `monto_ganado` | DECIMAL(38,2) | Monto total pagado del ticket | Derivado | sum(Win) de sus líneas |
| `live_cod` | INTEGER | 0 prepartido, 1 en vivo, 2 mixta (a validar) | Apuestas deportivas.Live |  |
| `canal` | VARCHAR | Canal (Mobile, Web, apk23, apk25) | Apuestas deportivas.Source |  |
| `con_fondos_bono` | INTEGER | Apuesta hecha con fondos de bono | Apuestas deportivas.Bonus Funds |  |
| `cashout` | INTEGER | Usó cashout | Apuestas deportivas.Cashout |  |
| `estado_ticket` | VARCHAR | Estado consolidado del ticket | Derivado | abierta si alguna línea Running/Reopen; anulada_o_reembolsada si todas Void/Refund; si no liquidada |
| `es_prueba` | INTEGER | Registro de prueba (vacío = no) | Test |  |

## `core.casino`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `ronda_id` | VARCHAR | Identificador de la ronda de casino | Apuestas Casino.Bet Id |  |
| `player_id` | VARCHAR | Jugador | Apuestas Casino.Client Id |  |
| `fecha_hora` | TIMESTAMP | Fecha y hora de la ronda | Apuestas Casino.Placed Date |  |
| `fecha_liquidacion` | TIMESTAMP | Fecha de liquidación | Apuestas Casino.Settled Date |  |
| `proveedor` | VARCHAR | Proveedor del juego | Apuestas Casino.Provider |  |
| `juego` | VARCHAR | Juego | Apuestas Casino.Game |  |
| `monto_apostado` | DECIMAL(18,2) | Monto apostado en la ronda (COP) | Apuestas Casino.Stake |  |
| `monto_ganado` | DECIMAL(18,2) | Monto pagado al jugador (COP) | Apuestas Casino.Win |  |
| `estado` | VARCHAR | Estado (CLOSED_WON, CLOSED_LOST, CLOSED_VOID, OPEN…) | Apuestas Casino.Status |  |
| `con_bono` | INTEGER | Ronda con bono | Apuestas Casino.Bonus |  |
| `es_prueba` | INTEGER | Registro de prueba (vacío = no) | Test |  |
| `origen_archivo` | VARCHAR | Archivo del que proviene la fila | Manifiesto |  |
| `origen_load_id` | INTEGER | Carga del manifiesto | Manifiesto |  |
| `origen_fila` | INTEGER | Fila del Excel (1 = encabezado) | Manifiesto |  |

## `core.jugador`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `player_id` | VARCHAR | Identificador del jugador (texto) | ID / Client ID |  |
| `en_registros` | BOOLEAN | Aparece en Registros (con datos de contacto) | Derivado |  |
| `en_recargas` | BOOLEAN | Tiene recargas cargadas | Derivado |  |
| `en_retiros` | BOOLEAN | Tiene retiros cargados | Derivado |  |
| `en_apuestas` | BOOLEAN | Tiene apuestas deportivas cargadas | Derivado |  |
| `en_casino` | BOOLEAN | Tiene rondas de casino cargadas | Derivado |  |
| `fecha_registro` | TIMESTAMP | Fecha de registro del jugador | core.registro / core.retiro |  |
| `fuente_fecha_registro` | VARCHAR | De dónde salió la fecha de registro | Derivado | registros > retiros > desconocida |

## `mart.jugador_resumen`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `player_id` | VARCHAR | Identificador del jugador (texto) | ID / Client ID |  |
| `fecha_corte` | TIMESTAMP | Fecha de corte del cálculo | Parámetro |  |
| `en_registros` | BOOLEAN | Aparece en Registros (con datos de contacto) | Derivado |  |
| `fecha_registro` | TIMESTAMP | Fecha de registro del jugador | core.registro / core.retiro |  |
| `fuente_fecha_registro` | VARCHAR | De dónde salió la fecha de registro | Derivado | registros > retiros > desconocida |
| `cohorte_registro` | VARCHAR | Mes de registro, 'antes_jul_2026' o 'desconocida' | Derivado |  |
| `antiguedad_dias` | BIGINT | Días desde el registro al corte | Derivado | corte - fecha_registro |
| `historia_completa` | BOOLEAN | Registrado dentro de la ventana: lo observado es su historia completa | Derivado | fecha_registro >= 1-jul-2026 |
| `estado_cuenta_cod` | INTEGER | Código de estado de la cuenta (1 = activa; negativos a validar) | Registros.Status | Active se normaliza a 1 |
| `kyc_cod` | INTEGER | Código KYC (significado a validar) | Registros.Kyc |  |
| `verificacion_celular_cod` | INTEGER | Verificación del celular: 30 verificado, 20 no verificado | Registros.Mobile Verification |  |
| `telefono_10` | VARCHAR | Celular normalizado a 10 dígitos | Registros.Mobilephone | Solo dígitos; 10 que inician en 3, o 12 que inician en 573 sin el 57; si no, NULL |
| `telefono_estado` | VARCHAR | Resultado de la normalización | Derivado | valido / valido_con_prefijo_57 / invalido_o_incompleto / vacio |
| `jugadores_mismo_telefono` | BIGINT | Cuántos player_id comparten el teléfono | Derivado | count(*) over (partition by telefono_10) |
| `edad_al_corte` | BIGINT | Edad en años al corte | Derivado | date_diff(year, fecha_nacimiento, corte) |
| `genero` | VARCHAR | Género declarado | Registros.Gender |  |
| `region` | VARCHAR | Región de residencia | Registros.Res Region |  |
| `departamento` | VARCHAR | Departamento de residencia | Registros.Res Department |  |
| `depositante_plataforma` | INTEGER | La plataforma lo marca como depositante a la fecha de exportación | Registros.Depositor |  |
| `fecha_primer_deposito_plataforma` | TIMESTAMP | Primer depósito histórico según la plataforma | Registros.First Dep. Date | Puede ser posterior al corte |
| `monto_primer_deposito_plataforma` | DECIMAL(18,2) | Monto del primer depósito histórico (COP) | Registros.First Dep. Amount |  |
| `promocode_registro` | VARCHAR | Código promocional/afiliado de registro | Registros.Promocode |  |
| `agent_id_registro` | VARCHAR | Agente del registro | Registros.Agent Id |  |
| `rec_n` | BIGINT | Recargas acreditadas en la ventana (0 = ninguna observada) | core.recarga | count(*) |
| `rec_monto` | DECIMAL(38,2) | Monto recargado en la ventana (no es ingreso de la empresa) | core.recarga | sum(monto) |
| `rec_promedio` | DOUBLE | Recarga promedio | core.recarga | avg(monto) |
| `rec_mediana` | DECIMAL(18,2) | Recarga mediana | core.recarga | median(monto) |
| `rec_primera_obs` | TIMESTAMP | Primera recarga observada en la ventana | core.recarga | min(fecha_hora) |
| `rec_ultima_obs` | TIMESTAMP | Última recarga observada | core.recarga | max(fecha_hora) |
| `rec_dias_desde_ultima` | BIGINT | Días desde la última recarga al corte | Derivado | corte - rec_ultima_obs |
| `rec_dias_activos` | BIGINT | Días distintos con recarga | core.recarga | count(distinct fecha) |
| `rec_intervalo_mediano_dias` | DOUBLE | Intervalo típico entre días con recarga | core.recarga | mediana de la diferencia entre días consecutivos |
| `rec_n_v1` | BIGINT | Recargas en los últimos 30 días (v1; v2 y v3 son las dos ventanas previas) | core.recarga | v1 = (corte-30d, corte] |
| `rec_n_v2` | BIGINT | Recargas en los últimos 30 días (v1; v2 y v3 son las dos ventanas previas) | core.recarga | v1 = (corte-30d, corte] |
| `rec_n_v3` | BIGINT | Recargas en los últimos 30 días (v1; v2 y v3 son las dos ventanas previas) | core.recarga | v1 = (corte-30d, corte] |
| `rec_monto_v1` | DECIMAL(38,2) | Monto recargado en v1 (v2, v3 análogos) | core.recarga |  |
| `rec_monto_v2` | DECIMAL(38,2) | Monto recargado en v1 (v2, v3 análogos) | core.recarga |  |
| `rec_monto_v3` | DECIMAL(38,2) | Monto recargado en v1 (v2, v3 análogos) | core.recarga |  |
| `rec_n_jul` | BIGINT | Recargas por mes calendario (jul/ago/sep) | core.recarga |  |
| `rec_n_ago` | BIGINT | Recargas por mes calendario (jul/ago/sep) | core.recarga |  |
| `rec_n_sep` | BIGINT | Recargas por mes calendario (jul/ago/sep) | core.recarga |  |
| `rec_metodo_principal` | VARCHAR | Medio de pago más usado | core.recarga | mode(metodo) |
| `rec_franja_principal` | VARCHAR | Franja horaria más frecuente de recarga | core.recarga | madrugada 0-5, mañana 6-11, tarde 12-17, noche 18-23 |
| `rec_pct_madrugada` | DOUBLE | Proporción de recargas entre 0 y 6 h | core.recarga |  |
| `rec_max_en_un_dia` | BIGINT | Máximo de recargas en un mismo día | core.recarga | Insumo de la señal de juego responsable |
| `apu_n` | BIGINT | Apuestas deportivas (tickets) en la ventana | core.apuesta | count(*) |
| `apu_monto` | DECIMAL(38,2) | Monto apostado en deportes | core.apuesta | sum(monto_apostado) |
| `apu_monto_mediano` | DECIMAL(38,2) | Apuesta mediana | core.apuesta | median(monto_apostado) |
| `apu_primera_obs` | TIMESTAMP | Primera apuesta observada | core.apuesta | min(fecha_hora) |
| `apu_ultima_obs` | TIMESTAMP | Última apuesta observada | core.apuesta | max(fecha_hora) |
| `apu_dias_desde_ultima` | BIGINT | Días desde la última apuesta | Derivado | corte - apu_ultima_obs |
| `apu_dias_activos` | BIGINT | Días distintos con apuesta | core.apuesta | count(distinct fecha) |
| `apu_intervalo_mediano_dias` | DOUBLE | Intervalo típico entre días con apuesta | core.apuesta | mediana de la diferencia entre días consecutivos |
| `apu_n_v1` | BIGINT | Apuestas en v1 (v2, v3 análogos) | core.apuesta | Ventanas de 30 días |
| `apu_n_v2` | BIGINT | Apuestas en v1 (v2, v3 análogos) | core.apuesta | Ventanas de 30 días |
| `apu_n_v3` | BIGINT | Apuestas en v1 (v2, v3 análogos) | core.apuesta | Ventanas de 30 días |
| `apu_dias_v1` | BIGINT | Días con apuesta en v1 (v2, v3 análogos) | core.apuesta |  |
| `apu_dias_v2` | BIGINT | Días con apuesta en v1 (v2, v3 análogos) | core.apuesta |  |
| `apu_dias_v3` | BIGINT | Días con apuesta en v1 (v2, v3 análogos) | core.apuesta |  |
| `apu_n_jul` | BIGINT | Apuestas por mes calendario (jul/ago/sep) | core.apuesta |  |
| `apu_n_ago` | BIGINT | Apuestas por mes calendario (jul/ago/sep) | core.apuesta |  |
| `apu_n_sep` | BIGINT | Apuestas por mes calendario (jul/ago/sep) | core.apuesta |  |
| `apu_pct_en_vivo` | DOUBLE | Proporción de apuestas en vivo | core.apuesta | avg(live_cod = 1) |
| `apu_pct_prepartido` | DOUBLE | Proporción de apuestas prepartido | core.apuesta | avg(live_cod = 0) |
| `apu_pct_simple` | DOUBLE | Proporción de apuestas simples | core.apuesta | avg(tipo = SINGLE) |
| `apu_selecciones_mediana` | DOUBLE | Selecciones típicas por apuesta | core.apuesta | median(selecciones) |
| `apu_pct_con_bono` | DOUBLE | Proporción de apuestas con fondos de bono | core.apuesta |  |
| `apu_pct_cashout` | DOUBLE | Proporción con cashout | core.apuesta |  |
| `apu_pct_fin_de_semana` | DOUBLE | Proporción de apuestas sábado-domingo | core.apuesta |  |
| `apu_canal_principal` | VARCHAR | Canal más usado | core.apuesta | mode(canal) |
| `apu_franja_principal` | VARCHAR | Franja horaria más frecuente de apuesta | core.apuesta |  |
| `apu_dia_semana_principal` | BIGINT | Día de la semana más frecuente (1 = lunes) | core.apuesta | mode(isodow) |
| `cas_n` | BIGINT | Rondas de casino en la ventana | core.casino | count(*) |
| `cas_monto` | DECIMAL(38,2) | Monto apostado en casino | core.casino | sum(monto_apostado) |
| `cas_dias_activos` | BIGINT | Días distintos con casino | core.casino | count(distinct fecha) |
| `cas_primera_obs` | TIMESTAMP | Primera ronda de casino observada | core.casino | min(fecha_hora) |
| `cas_ultima_obs` | TIMESTAMP | Última ronda de casino observada | core.casino | max(fecha_hora) |
| `cas_proveedor_principal` | VARCHAR | Proveedor de casino más usado | core.casino | mode(proveedor) |
| `cas_juego_principal` | VARCHAR | Juego de casino más jugado | core.casino | mode(juego) |
| `ret_n` | BIGINT | Retiros procesados en la ventana | core.retiro | count(*) |
| `ret_monto_neto` | DECIMAL(38,2) | Monto neto retirado | core.retiro | sum(monto_neto) |
| `ret_primera_obs` | TIMESTAMP | Primera solicitud de retiro observada | core.retiro | min(fecha_solicitud) |
| `ret_ultima_obs` | TIMESTAMP | Última solicitud de retiro observada | core.retiro | max(fecha_solicitud) |
| `ret_minutos_mediana` | DOUBLE | Tiempo mediano de procesamiento | core.retiro | median(minutos) |
| `ret_metodo_principal` | VARCHAR | Medio de retiro más usado | core.retiro | mode(metodo) |
| `horas_registro_a_primera_recarga` | BIGINT | Horas entre registro y primera recarga (solo historia completa) | Derivado |  |
| `horas_registro_a_primera_apuesta` | BIGINT | Horas entre registro y primera apuesta (solo historia completa) | Derivado |  |
| `horas_primera_recarga_a_primera_apuesta` | BIGINT | Horas entre primera recarga y primera apuesta | Derivado | Negativo = apostó antes de recargar |
| `activo_v1` | BOOLEAN | Tuvo recarga, apuesta o casino en v1 (v2, v3 análogos) | Derivado |  |
| `activo_v2` | BOOLEAN | Tuvo recarga, apuesta o casino en v1 (v2, v3 análogos) | Derivado |  |
| `activo_v3` | BOOLEAN | Tuvo recarga, apuesta o casino en v1 (v2, v3 análogos) | Derivado |  |
| `ventanas_elegibles` | INTEGER | Ventanas de 30 días en las que ya estaba registrado | Derivado | Evita contar como inactivo a quien no existía |
| `ultima_actividad_obs` | TIMESTAMP | Última recarga, apuesta o ronda de casino | Derivado | greatest(rec, apu, cas) |
| `dias_desde_ultima_actividad` | BIGINT | Recencia de actividad | Derivado | corte - ultima_actividad_obs |
| `patron_actividad` | VARCHAR | Actividad en v3-v2-v1 (1 activo, 0 inactivo, x no registrado) | Derivado | Ej. 1-0-1 = retorno |

## `mart.segmento_jugador`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `player_id` | VARCHAR | Identificador del jugador (texto) | ID / Client ID |  |
| `fecha_corte` | TIMESTAMP | Fecha de corte del cálculo | Parámetro |  |
| `version_reglas` | VARCHAR | Versión de reglas | Parámetro |  |
| `calculado_en` | TIMESTAMP | Momento del cálculo | Sistema |  |
| `ciclo_vida` | VARCHAR | Segmento amplio excluyente | Derivado | Ver módulo Segmentos de la app |
| `nivel_valor` | VARCHAR | Nivel por monto recargado (p50/p90) | Derivado | Solo descriptivo |
| `h_sin_recarga_0_7d` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_sin_recarga_8_30d` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_sin_recarga_31d_mas` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_deposito_posterior_al_corte` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_recarga_sin_apuesta_deportiva` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_una_sola_recarga` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_atrasado_vs_ritmo_propio` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_caida_de_frecuencia` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_retorno` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `h_continuo_3_ventanas` | BOOLEAN | Hipersegmento (etiqueta booleana) | Derivado | Ver módulo Segmentos de la app |
| `pref_modalidad` | VARCHAR | Preferencia en vivo / prepartido (≥ 5 apuestas, ≥ 60 %) | Derivado |  |
| `pref_tipo_apuesta` | VARCHAR | Preferencia simples / combinadas (≥ 70 % / ≤ 30 % simples) | Derivado |  |
| `pref_fin_de_semana` | BOOLEAN | ≥ 50 % de sus apuestas en sábado-domingo | Derivado | Requiere ≥ 5 apuestas |
| `franja_habitual` | VARCHAR | Franja habitual para elegir hora de envío | Derivado | apuestas > recargas > hora de registro |
| `senal_revision_juego_responsable` | BOOLEAN | Señal que excluye de comunicaciones promocionales | Derivado | p99 recargas/día, madrugada o escalada |
| `estado_contacto` | VARCHAR | Contactabilidad con los datos disponibles | Derivado |  |

## `mart.audiencia_sms`

| Campo | Tipo | Definición | Origen | Fórmula / regla |
|---|---|---|---|---|
| `campana` | VARCHAR | Código de campaña | mart.campana_catalogo |  |
| `player_id` | VARCHAR | Identificador del jugador (texto) | ID / Client ID |  |
| `telefono` | VARCHAR | Celular normalizado de 10 dígitos | core.registro.telefono_10 |  |
| `grupo` | VARCHAR | envio o control | Derivado | hash(player_id + semilla + campaña) % 100 < pct_control |
| `variante_copy` | VARCHAR | Variante de mensaje según preferencia | Derivado | en_vivo / prepartido / general |
| `franja_habitual` | VARCHAR | Franja habitual para elegir hora de envío | Derivado | apuestas > recargas > hora de registro |
| `ventana_envio_sugerida` | VARCHAR | Ventana de envío dentro del horario legal | Derivado | Según franja_habitual; lun-vie 7-19 h, sáb 8-15 h |
| `motivo_inclusion` | VARCHAR | Motivo legible de inclusión | Derivado |  |
| `fecha_corte` | TIMESTAMP | Fecha de corte del cálculo | Parámetro |  |
| `version_reglas` | VARCHAR | Versión de reglas | Parámetro |  |
| `estado_activacion` | VARCHAR | Bloqueo hasta validar consentimiento y autoexclusión | Derivado |  |
