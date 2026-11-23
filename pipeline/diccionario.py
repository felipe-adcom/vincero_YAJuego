"""Genera el diccionario de datos (docs/03_diccionario_datos.md y reports/diccionario_datos.csv).

Los tipos se leen de la base; las definiciones, orígenes y fórmulas viven aquí. Si una
columna nueva no tiene definición, aparece marcada como PENDIENTE para no quedar oculta.

    python pipeline/diccionario.py
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH, REPORT_DIR, ROOT  # noqa: E402

R, RC, RT, AP, CA = "Registros", "Recargas", "Retiros", "Apuestas deportivas", "Apuestas Casino"
# (tabla, columna): (definición, origen, fórmula/regla)
D = {
 # ---------- core.registro ----------
 ("core.registro", "player_id"): ("Identificador del jugador", f"{R}.ID", "Texto"),
 ("core.registro", "fecha_registro"): ("Fecha y hora de creación de la cuenta", f"{R}.Insert Date", ""),
 ("core.registro", "estado_cuenta_cod"): ("Código de estado de la cuenta (1 = activa; negativos a validar)", f"{R}.Status", "Active se normaliza a 1"),
 ("core.registro", "estado_cuenta_txt"): ("Estado de cuenta tal como llega (código hasta sep; texto Active/Suspended desde oct)", f"{R}.Status", ""),
 ("core.registro", "kyc_cod"): ("Código KYC (significado a validar)", f"{R}.Kyc", ""),
 ("core.registro", "kyc_doc_cod"): ("Estado de documentos KYC (a validar)", f"{R}.Kyc Doc Status", ""),
 ("core.registro", "verificacion_celular_cod"): ("Verificación del celular: 30 verificado, 20 no verificado", f"{R}.Mobile Verification", ""),
 ("core.registro", "fecha_verificacion_celular"): ("Fecha de verificación del celular", f"{R}.Mobile Verification Date", ""),
 ("core.registro", "fuente_registro_cod"): ("Código de fuente de registro (12/13, a validar)", f"{R}.Registration Source", ""),
 ("core.registro", "promocode_registro"): ("Código promocional/afiliado de registro", f"{R}.Promocode", ""),
 ("core.registro", "btag"): ("Etiqueta de afiliación", f"{R}.BTAG", ""),
 ("core.registro", "vip"): ("Marca VIP", f"{R}.Vip", ""),
 ("core.registro", "depositante_plataforma"): ("La plataforma lo marca como depositante a la fecha de exportación", f"{R}.Depositor", ""),
 ("core.registro", "fecha_primer_deposito_plataforma"): ("Primer depósito histórico según la plataforma", f"{R}.First Dep. Date", "Puede ser posterior al corte"),
 ("core.registro", "monto_primer_deposito_plataforma"): ("Monto del primer depósito histórico (COP)", f"{R}.First Dep. Amount", ""),
 ("core.registro", "saldo_al_exportar"): ("Saldo a la fecha de exportación, no al corte", f"{R}.Balance", "No usar para segmentar"),
 ("core.registro", "ultimo_login_al_exportar"): ("Último login a la fecha de exportación", f"{R}.Last Login", ""),
 ("core.registro", "intentos_login_fallidos"): ("Intentos fallidos de login", f"{R}.Failed Login Attempts", ""),
 ("core.registro", "fecha_nacimiento"): ("Fecha de nacimiento", f"{R}.Dob", ""),
 ("core.registro", "genero"): ("Género declarado", f"{R}.Gender", ""),
 ("core.registro", "nacionalidad"): ("Nacionalidad", f"{R}.Nationality", ""),
 ("core.registro", "region"): ("Región de residencia", f"{R}.Res Region", ""),
 ("core.registro", "departamento"): ("Departamento de residencia", f"{R}.Res Department", ""),
 ("core.registro", "ciudad"): ("Ciudad de residencia", f"{R}.Res City", ""),
 ("core.registro", "tipo_documento_cod"): ("Tipo de documento (código)", f"{R}.Document Type", ""),
 ("core.registro", "documento_hash"): ("Huella del documento, solo para detectar cuentas duplicadas", f"{R}.Document Id", "md5(lower(trim(Document Id)))"),
 ("core.registro", "email"): ("Correo en minúsculas", f"{R}.Email", "lower(trim(Email))"),
 ("core.registro", "telefono_original"): ("Teléfono tal como llegó", f"{R}.Mobilephone", ""),
 ("core.registro", "telefono_10"): ("Celular normalizado a 10 dígitos", f"{R}.Mobilephone", "Solo dígitos; 10 que inician en 3, o 12 que inician en 573 sin el 57; si no, NULL"),
 ("core.registro", "telefono_estado"): ("Resultado de la normalización", "Derivado", "valido / valido_con_prefijo_57 / invalido_o_incompleto / vacio"),
 ("core.registro", "fecha_actualizacion_registro"): ("Última actualización del registro", f"{R}.Update Date", ""),
 ("core.registro", "usuario_actualizacion_registro"): ("Usuario u operador que actualizó", f"{R}.Update User", ""),
 ("core.registro", "jugadores_mismo_telefono"): ("Cuántos player_id comparten el teléfono", "Derivado", "count(*) over (partition by telefono_10)"),
 ("core.registro", "jugadores_mismo_email"): ("Cuántos player_id comparten el correo", "Derivado", "count(*) over (partition by email)"),
 ("core.registro", "jugadores_mismo_documento"): ("Cuántos player_id comparten documento", "Derivado", "count(*) over (partition by documento_hash)"),
 # ---------- core.recarga ----------
 ("core.recarga", "recarga_id"): ("Identificador de la recarga", f"{RC}.Id", ""),
 ("core.recarga", "player_id"): ("Jugador", f"{RC}.Client ID", ""),
 ("core.recarga", "fecha_hora"): ("Fecha y hora de la recarga (hora local supuesta)", f"{RC}.Insert Date", ""),
 ("core.recarga", "monto"): ("Monto acreditado (COP)", f"{RC}.Amount", ""),
 ("core.recarga", "cargo"): ("Cargo cobrado", f"{RC}.Charge", ""),
 ("core.recarga", "metodo"): ("Medio de pago", f"{RC}.Method", ""),
 ("core.recarga", "estado"): ("Estado de la operación", f"{RC}.Status", "Solo CREDITED en los exports"),
 ("core.recarga", "es_manual"): ("Recarga manual", f"{RC}.Manual", ""),
 # ---------- core.retiro ----------
 ("core.retiro", "retiro_id"): ("Identificador del retiro", f"{RT}.Id", ""),
 ("core.retiro", "player_id"): ("Jugador", f"{RT}.Client ID", ""),
 ("core.retiro", "fecha_solicitud"): ("Fecha de la solicitud", f"{RT}.Insert Date", ""),
 ("core.retiro", "fecha_ultima_actualizacion"): ("Fecha de procesamiento; define el periodo del archivo", f"{RT}.Last Update", ""),
 ("core.retiro", "minutos_hasta_actualizacion"): ("Tiempo de procesamiento observado", "Derivado", "Last Update - Insert Date (minutos)"),
 ("core.retiro", "estado"): ("Estado", f"{RT}.Status", "Solo PROCESSED en los exports"),
 ("core.retiro", "metodo"): ("Medio de pago del retiro", f"{RT}.Method", ""),
 ("core.retiro", "monto_solicitado"): ("Monto solicitado (COP)", f"{RT}.Requested Amount", ""),
 ("core.retiro", "monto_neto"): ("Monto neto pagado (COP)", f"{RT}.Net Amount", "Solicitado - impuesto"),
 ("core.retiro", "impuesto"): ("Retención aplicada", f"{RT}.Tax", ""),
 ("core.retiro", "comision"): ("Comisión", f"{RT}.Deposit Fee", ""),
 ("core.retiro", "perfil_retiro"): ("Perfil/grupo del jugador al retirar (a validar)", f"{RT}.Profile", ""),
 ("core.retiro", "nivel_riesgo_cod"): ("Nivel de riesgo (a validar)", f"{RT}.Risk Level", ""),
 ("core.retiro", "ultimo_operador"): ("Último operador", f"{RT}.Last Operator", ""),
 ("core.retiro", "es_manual"): ("Retiro manual", f"{RT}.Is Manual", ""),
 ("core.retiro", "fecha_registro_reportada"): ("Fecha de registro del jugador según Retiros", f"{RT}.Registration Date", ""),
 # ---------- core.apuesta_linea / core.apuesta ----------
 ("core.apuesta_linea", "bet_id"): ("Identificador de la apuesta (ticket)", f"{AP}.Bet ID", ""),
 ("core.apuesta_linea", "tipo_linea"): ("Tipo de línea (SINGLE 1, MULTIPLE n, COMB n, SYSTEM n)", f"{AP}.Bet Type", "Llave: bet_id + tipo_linea"),
 ("core.apuesta_linea", "fecha_hora"): ("Fecha y hora de colocación", f"{AP}.Insert Date", ""),
 ("core.apuesta_linea", "fecha_liquidacion"): ("Fecha de liquidación", f"{AP}.Settled Date", ""),
 ("core.apuesta_linea", "fecha_pago"): ("Fecha de pago", f"{AP}.Paid Date", ""),
 ("core.apuesta_linea", "fecha_actualizacion"): ("Última actualización", f"{AP}.Update Date", ""),
 ("core.apuesta_linea", "estado"): ("Estado de la línea (Win, Lose, Refund, Void, Running, Reopen…)", f"{AP}.Status", ""),
 ("core.apuesta_linea", "motivo_anulacion"): ("Motivo de anulación", f"{AP}.Void Reason", ""),
 ("core.apuesta_linea", "monto_apostado"): ("Monto apostado en la línea (COP)", f"{AP}.Stake", ""),
 ("core.apuesta_linea", "monto_ganado"): ("Monto pagado al jugador (COP)", f"{AP}.Win", ""),
 ("core.apuesta_linea", "ganancia_potencial"): ("Ganancia potencial", f"{AP}.Pot Win", ""),
 ("core.apuesta_linea", "cuota_total"): ("Cuota total", f"{AP}.Total Odd", ""),
 ("core.apuesta_linea", "tipo_apuesta"): ("SINGLE, MULTIPLE, COMB o SYSTEM", f"{AP}.Bet Type", "Primera palabra de Bet Type"),
 ("core.apuesta_linea", "selecciones"): ("Número de selecciones", f"{AP}.Numlines", ""),
 ("core.apuesta_linea", "live_cod"): ("0 prepartido, 1 en vivo, 2 mixta (a validar)", f"{AP}.Live", ""),
 ("core.apuesta_linea", "canal"): ("Canal (Mobile, Web, apk23, apk25)", f"{AP}.Source", ""),
 ("core.apuesta_linea", "con_fondos_bono"): ("Apuesta hecha con fondos de bono", f"{AP}.Bonus Funds", ""),
 ("core.apuesta_linea", "bonus_id"): ("Bono usado", f"{AP}.Bonus Id", ""),
 ("core.apuesta_linea", "cashout"): ("Usó cashout", f"{AP}.Cashout", ""),
 ("core.apuesta", "estado_ticket"): ("Estado consolidado del ticket", "Derivado", "abierta si alguna línea Running/Reopen; anulada_o_reembolsada si todas Void/Refund; si no liquidada"),
 ("core.apuesta", "lineas"): ("Líneas del ticket (SYSTEM tiene varias)", "Derivado", "count(*) por bet_id"),
 ("core.apuesta", "monto_apostado"): ("Monto total del ticket", "Derivado", "sum(Stake) de sus líneas"),
 ("core.apuesta", "monto_ganado"): ("Monto total pagado del ticket", "Derivado", "sum(Win) de sus líneas"),
 # ---------- core.casino ----------
 ("core.casino", "ronda_id"): ("Identificador de la ronda de casino", f"{CA}.Bet Id", ""),
 ("core.casino", "player_id"): ("Jugador", f"{CA}.Client Id", ""),
 ("core.casino", "fecha_hora"): ("Fecha y hora de la ronda", f"{CA}.Placed Date", ""),
 ("core.casino", "fecha_liquidacion"): ("Fecha de liquidación", f"{CA}.Settled Date", ""),
 ("core.casino", "proveedor"): ("Proveedor del juego", f"{CA}.Provider", ""),
 ("core.casino", "juego"): ("Juego", f"{CA}.Game", ""),
 ("core.casino", "monto_apostado"): ("Monto apostado en la ronda (COP)", f"{CA}.Stake", ""),
 ("core.casino", "monto_ganado"): ("Monto pagado al jugador (COP)", f"{CA}.Win", ""),
 ("core.casino", "estado"): ("Estado (CLOSED_WON, CLOSED_LOST, CLOSED_VOID, OPEN…)", f"{CA}.Status", ""),
 ("core.casino", "con_bono"): ("Ronda con bono", f"{CA}.Bonus", ""),
 # ---------- core.jugador ----------
 ("core.jugador", "en_registros"): ("Aparece en Registros (con datos de contacto)", "Derivado", ""),
 ("core.jugador", "en_recargas"): ("Tiene recargas cargadas", "Derivado", ""),
 ("core.jugador", "en_retiros"): ("Tiene retiros cargados", "Derivado", ""),
 ("core.jugador", "en_apuestas"): ("Tiene apuestas deportivas cargadas", "Derivado", ""),
 ("core.jugador", "en_casino"): ("Tiene rondas de casino cargadas", "Derivado", ""),
 ("core.jugador", "fuente_fecha_registro"): ("De dónde salió la fecha de registro", "Derivado", "registros > retiros > desconocida"),
 # ---------- mart.jugador_resumen ----------
 ("mart.jugador_resumen", "cohorte_registro"): ("Mes de registro, 'antes_jul_2026' o 'desconocida'", "Derivado", ""),
 ("mart.jugador_resumen", "antiguedad_dias"): ("Días desde el registro al corte", "Derivado", "corte - fecha_registro"),
 ("mart.jugador_resumen", "historia_completa"): ("Registrado dentro de la ventana: lo observado es su historia completa", "Derivado", "fecha_registro >= 1-jul-2026"),
 ("mart.jugador_resumen", "edad_al_corte"): ("Edad en años al corte", "Derivado", "date_diff(year, fecha_nacimiento, corte)"),
 ("mart.jugador_resumen", "agent_id_registro"): ("Agente del registro", f"{R}.Agent Id", ""),
 ("mart.jugador_resumen", "rec_n"): ("Recargas acreditadas en la ventana (0 = ninguna observada)", "core.recarga", "count(*)"),
 ("mart.jugador_resumen", "rec_monto"): ("Monto recargado en la ventana (no es ingreso de la empresa)", "core.recarga", "sum(monto)"),
 ("mart.jugador_resumen", "rec_promedio"): ("Recarga promedio", "core.recarga", "avg(monto)"),
 ("mart.jugador_resumen", "rec_mediana"): ("Recarga mediana", "core.recarga", "median(monto)"),
 ("mart.jugador_resumen", "rec_primera_obs"): ("Primera recarga observada en la ventana", "core.recarga", "min(fecha_hora)"),
 ("mart.jugador_resumen", "rec_ultima_obs"): ("Última recarga observada", "core.recarga", "max(fecha_hora)"),
 ("mart.jugador_resumen", "rec_dias_desde_ultima"): ("Días desde la última recarga al corte", "Derivado", "corte - rec_ultima_obs"),
 ("mart.jugador_resumen", "rec_dias_activos"): ("Días distintos con recarga", "core.recarga", "count(distinct fecha)"),
 ("mart.jugador_resumen", "rec_intervalo_mediano_dias"): ("Intervalo típico entre días con recarga", "core.recarga", "mediana de la diferencia entre días consecutivos"),
 ("mart.jugador_resumen", "rec_n_v1"): ("Recargas en los últimos 30 días (v1; v2 y v3 son las dos ventanas previas)", "core.recarga", "v1 = (corte-30d, corte]"),
 ("mart.jugador_resumen", "rec_monto_v1"): ("Monto recargado en v1 (v2, v3 análogos)", "core.recarga", ""),
 ("mart.jugador_resumen", "rec_n_jul"): ("Recargas por mes calendario (jul/ago/sep)", "core.recarga", ""),
 ("mart.jugador_resumen", "rec_metodo_principal"): ("Medio de pago más usado", "core.recarga", "mode(metodo)"),
 ("mart.jugador_resumen", "rec_franja_principal"): ("Franja horaria más frecuente de recarga", "core.recarga", "madrugada 0-5, mañana 6-11, tarde 12-17, noche 18-23"),
 ("mart.jugador_resumen", "rec_pct_madrugada"): ("Proporción de recargas entre 0 y 6 h", "core.recarga", ""),
 ("mart.jugador_resumen", "rec_max_en_un_dia"): ("Máximo de recargas en un mismo día", "core.recarga", "Insumo de la señal de juego responsable"),
 ("mart.jugador_resumen", "apu_n"): ("Apuestas deportivas (tickets) en la ventana", "core.apuesta", "count(*)"),
 ("mart.jugador_resumen", "apu_monto"): ("Monto apostado en deportes", "core.apuesta", "sum(monto_apostado)"),
 ("mart.jugador_resumen", "apu_monto_mediano"): ("Apuesta mediana", "core.apuesta", "median(monto_apostado)"),
 ("mart.jugador_resumen", "apu_primera_obs"): ("Primera apuesta observada", "core.apuesta", "min(fecha_hora)"),
 ("mart.jugador_resumen", "apu_ultima_obs"): ("Última apuesta observada", "core.apuesta", "max(fecha_hora)"),
 ("mart.jugador_resumen", "apu_dias_desde_ultima"): ("Días desde la última apuesta", "Derivado", "corte - apu_ultima_obs"),
 ("mart.jugador_resumen", "apu_dias_activos"): ("Días distintos con apuesta", "core.apuesta", "count(distinct fecha)"),
 ("mart.jugador_resumen", "apu_intervalo_mediano_dias"): ("Intervalo típico entre días con apuesta", "core.apuesta", "mediana de la diferencia entre días consecutivos"),
 ("mart.jugador_resumen", "apu_n_v1"): ("Apuestas en v1 (v2, v3 análogos)", "core.apuesta", "Ventanas de 30 días"),
 ("mart.jugador_resumen", "apu_dias_v1"): ("Días con apuesta en v1 (v2, v3 análogos)", "core.apuesta", ""),
 ("mart.jugador_resumen", "apu_n_jul"): ("Apuestas por mes calendario (jul/ago/sep)", "core.apuesta", ""),
 ("mart.jugador_resumen", "apu_pct_en_vivo"): ("Proporción de apuestas en vivo", "core.apuesta", "avg(live_cod = 1)"),
 ("mart.jugador_resumen", "apu_pct_prepartido"): ("Proporción de apuestas prepartido", "core.apuesta", "avg(live_cod = 0)"),
 ("mart.jugador_resumen", "apu_pct_simple"): ("Proporción de apuestas simples", "core.apuesta", "avg(tipo = SINGLE)"),
 ("mart.jugador_resumen", "apu_selecciones_mediana"): ("Selecciones típicas por apuesta", "core.apuesta", "median(selecciones)"),
 ("mart.jugador_resumen", "apu_pct_con_bono"): ("Proporción de apuestas con fondos de bono", "core.apuesta", ""),
 ("mart.jugador_resumen", "apu_pct_cashout"): ("Proporción con cashout", "core.apuesta", ""),
 ("mart.jugador_resumen", "apu_pct_fin_de_semana"): ("Proporción de apuestas sábado-domingo", "core.apuesta", ""),
 ("mart.jugador_resumen", "apu_canal_principal"): ("Canal más usado", "core.apuesta", "mode(canal)"),
 ("mart.jugador_resumen", "apu_franja_principal"): ("Franja horaria más frecuente de apuesta", "core.apuesta", ""),
 ("mart.jugador_resumen", "apu_dia_semana_principal"): ("Día de la semana más frecuente (1 = lunes)", "core.apuesta", "mode(isodow)"),
 ("mart.jugador_resumen", "cas_n"): ("Rondas de casino en la ventana", "core.casino", "count(*)"),
 ("mart.jugador_resumen", "cas_monto"): ("Monto apostado en casino", "core.casino", "sum(monto_apostado)"),
 ("mart.jugador_resumen", "cas_dias_activos"): ("Días distintos con casino", "core.casino", "count(distinct fecha)"),
 ("mart.jugador_resumen", "cas_primera_obs"): ("Primera ronda de casino observada", "core.casino", "min(fecha_hora)"),
 ("mart.jugador_resumen", "cas_ultima_obs"): ("Última ronda de casino observada", "core.casino", "max(fecha_hora)"),
 ("mart.jugador_resumen", "cas_proveedor_principal"): ("Proveedor de casino más usado", "core.casino", "mode(proveedor)"),
 ("mart.jugador_resumen", "cas_juego_principal"): ("Juego de casino más jugado", "core.casino", "mode(juego)"),
 ("mart.jugador_resumen", "ret_n"): ("Retiros procesados en la ventana", "core.retiro", "count(*)"),
 ("mart.jugador_resumen", "ret_monto_neto"): ("Monto neto retirado", "core.retiro", "sum(monto_neto)"),
 ("mart.jugador_resumen", "ret_primera_obs"): ("Primera solicitud de retiro observada", "core.retiro", "min(fecha_solicitud)"),
 ("mart.jugador_resumen", "ret_ultima_obs"): ("Última solicitud de retiro observada", "core.retiro", "max(fecha_solicitud)"),
 ("mart.jugador_resumen", "ret_minutos_mediana"): ("Tiempo mediano de procesamiento", "core.retiro", "median(minutos)"),
 ("mart.jugador_resumen", "ret_metodo_principal"): ("Medio de retiro más usado", "core.retiro", "mode(metodo)"),
 ("mart.jugador_resumen", "horas_registro_a_primera_recarga"): ("Horas entre registro y primera recarga (solo historia completa)", "Derivado", ""),
 ("mart.jugador_resumen", "horas_registro_a_primera_apuesta"): ("Horas entre registro y primera apuesta (solo historia completa)", "Derivado", ""),
 ("mart.jugador_resumen", "horas_primera_recarga_a_primera_apuesta"): ("Horas entre primera recarga y primera apuesta", "Derivado", "Negativo = apostó antes de recargar"),
 ("mart.jugador_resumen", "activo_v1"): ("Tuvo recarga, apuesta o casino en v1 (v2, v3 análogos)", "Derivado", ""),
 ("mart.jugador_resumen", "ventanas_elegibles"): ("Ventanas de 30 días en las que ya estaba registrado", "Derivado", "Evita contar como inactivo a quien no existía"),
 ("mart.jugador_resumen", "ultima_actividad_obs"): ("Última recarga, apuesta o ronda de casino", "Derivado", "greatest(rec, apu, cas)"),
 ("mart.jugador_resumen", "dias_desde_ultima_actividad"): ("Recencia de actividad", "Derivado", "corte - ultima_actividad_obs"),
 ("mart.jugador_resumen", "patron_actividad"): ("Actividad en v3-v2-v1 (1 activo, 0 inactivo, x no registrado)", "Derivado", "Ej. 1-0-1 = retorno"),
 # ---------- mart.segmento_jugador ----------
 ("mart.segmento_jugador", "calculado_en"): ("Momento del cálculo", "Sistema", ""),
 ("mart.segmento_jugador", "ciclo_vida"): ("Segmento amplio excluyente", "Derivado", "Ver módulo Segmentos de la app"),
 ("mart.segmento_jugador", "nivel_valor"): ("Nivel por monto recargado (p50/p90)", "Derivado", "Solo descriptivo"),
 ("mart.segmento_jugador", "senal_revision_juego_responsable"): ("Señal que excluye de comunicaciones promocionales", "Derivado", "p99 recargas/día, madrugada o escalada"),
 ("mart.segmento_jugador", "estado_contacto"): ("Contactabilidad con los datos disponibles", "Derivado", ""),
 ("mart.segmento_jugador", "pref_modalidad"): ("Preferencia en vivo / prepartido (≥ 5 apuestas, ≥ 60 %)", "Derivado", ""),
 ("mart.segmento_jugador", "pref_tipo_apuesta"): ("Preferencia simples / combinadas (≥ 70 % / ≤ 30 % simples)", "Derivado", ""),
 ("mart.segmento_jugador", "pref_fin_de_semana"): ("≥ 50 % de sus apuestas en sábado-domingo", "Derivado", "Requiere ≥ 5 apuestas"),
 ("mart.segmento_jugador", "franja_habitual"): ("Franja habitual para elegir hora de envío", "Derivado", "apuestas > recargas > hora de registro"),
 # ---------- mart.audiencia_sms ----------
 ("mart.audiencia_sms", "campana"): ("Código de campaña", "mart.campana_catalogo", ""),
 ("mart.audiencia_sms", "telefono"): ("Celular normalizado de 10 dígitos", "core.registro.telefono_10", ""),
 ("mart.audiencia_sms", "grupo"): ("envio o control", "Derivado", "hash(player_id + semilla + campaña) % 100 < pct_control"),
 ("mart.audiencia_sms", "variante_copy"): ("Variante de mensaje según preferencia", "Derivado", "en_vivo / prepartido / general"),
 ("mart.audiencia_sms", "ventana_envio_sugerida"): ("Ventana de envío dentro del horario legal", "Derivado", "Según franja_habitual; lun-vie 7-19 h, sáb 8-15 h"),
 ("mart.audiencia_sms", "motivo_inclusion"): ("Motivo legible de inclusión", "Derivado", ""),
 ("mart.audiencia_sms", "estado_activacion"): ("Bloqueo hasta validar consentimiento y autoexclusión", "Derivado", ""),
}
COMUNES = {
    "origen_archivo": ("Archivo del que proviene la fila", "Manifiesto", ""),
    "origen_load_id": ("Carga del manifiesto", "Manifiesto", ""),
    "origen_fila": ("Fila del Excel (1 = encabezado)", "Manifiesto", ""),
    "es_prueba": ("Registro de prueba (vacío = no)", "Test", ""),
    "agent_id": ("Agente", "Agent ID", ""), "network_id": ("Red", "Network ID", ""),
    "promocode": ("Código promocional", "Promocode", ""),
    "player_id": ("Identificador del jugador (texto)", "ID / Client ID", ""),
    "en_registros": ("Aparece en Registros (con datos de contacto)", "Derivado", ""),
    "fuente_fecha_registro": ("De dónde salió la fecha de registro", "Derivado", "registros > retiros > desconocida"),
    "fecha_registro": ("Fecha de registro del jugador", "core.registro / core.retiro", ""),
    "fecha_corte": ("Fecha de corte del cálculo", "Parámetro", ""),
    "version_reglas": ("Versión de reglas", "Parámetro", ""),
    "fecha_hora": ("Fecha y hora de la operación", "Origen", ""),
}

TABLAS = ["core.registro", "core.recarga", "core.retiro", "core.apuesta_linea", "core.apuesta", "core.casino", "core.jugador",
          "mart.jugador_resumen", "mart.segmento_jugador", "mart.audiencia_sms"]


def buscar(tabla, col):
    if (tabla, col) in D:
        return D[(tabla, col)]
    base = col.replace("_v2", "_v1").replace("_v3", "_v1").replace("_ago", "_jul").replace("_sep", "_jul")
    if (tabla, base) in D:
        return D[(tabla, base)]
    if col in COMUNES:
        return COMUNES[col]
    for t in ("core.registro", "core.apuesta_linea", "mart.jugador_resumen", "mart.segmento_jugador"):
        if (t, col) in D:
            return D[(t, col)]
    if col.startswith("h_"):
        return ("Hipersegmento (etiqueta booleana)", "Derivado", "Ver módulo Segmentos de la app")
    return ("PENDIENTE de documentar", "", "")


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    filas = []
    for t in TABLAS:
        esquema, nombre = t.split(".")
        for col, tipo in con.execute(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
                [esquema, nombre]).fetchall():
            d, o, f = buscar(t, col)
            filas.append(dict(tabla=t, campo=col, tipo=tipo, definicion=d, origen=o, formula=f))
    con.close()
    df = pd.DataFrame(filas)
    df.to_csv(REPORT_DIR / "diccionario_datos.csv", index=False)
    md = ["# Diccionario de datos", "",
          "Generado con `python pipeline/diccionario.py` a partir de la base: los tipos son los reales.",
          "Las tablas `stg.*` conservan las columnas originales en texto (`snake_case` del encabezado) más",
          "`_load_id`, `_archivo`, `_sha256` y `_fila`. Versión CSV: `reports/diccionario_datos.csv`.", ""]
    for t, g in df.groupby("tabla", sort=False):
        md += [f"## `{t}`", "", "| Campo | Tipo | Definición | Origen | Fórmula / regla |", "|---|---|---|---|---|"]
        md += [f"| `{r.campo}` | {r.tipo} | {r.definicion} | {r.origen} | {r.formula} |" for r in g.itertuples()]
        md.append("")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "03_diccionario_datos.md").write_text("\n".join(md), encoding="utf-8")
    pend = (df.definicion.str.startswith("PENDIENTE")).sum()
    print(f"[ok] diccionario: {len(df)} campos, {pend} pendientes de documentar")
    if pend:
        print(df[df.definicion.str.startswith("PENDIENTE")][["tabla", "campo"]].to_string())


if __name__ == "__main__":
    main()
