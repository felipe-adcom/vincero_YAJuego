# Vincero · YAjuego: datos consolidados, segmentación y microcampañas SMS

Pipeline que consolida las bases operativas de YAjuego (registros, recargas, apuestas deportivas,
retiros y casino), calcula un perfil por jugador, asigna segmentos y genera audiencias SMS medibles
con grupo de control. Produce además la aplicación HTML de Vincero para el cliente.

Este repositorio contiene **solo código, reglas y documentación técnica**. Los archivos de origen,
la base, las audiencias, las tablas de resultados y la aplicación con cifras del cliente no se versionan.

## Estructura

```
data/raw/          originales intactos (no versionados: contienen datos personales)
data/warehouse/    yajuego.duckdb: stg, core, mart (al corte) y meta (manifiesto, controles, cobertura por día)
data/exports/      perfil por jugador, audiencias SMS y libro Excel (no versionados)
sql/               transformación, perfil por jugador, segmentos y audiencias
pipeline/          ingesta, orquestador, controles, exportes, análisis, diccionario y app
campanas/          copies SMS por campaña y variante
reports/           salidas agregadas y app (no versionadas); assets/ con la marca Vincero
tests/             prueba de la ingesta con archivos sintéticos
docs/              arquitectura y modelo
```

## Ejecutar

```bash
pip install duckdb pandas python-calamine openpyxl matplotlib
cp /ruta/a/los/excel/*.xlsx data/raw/          # sin renombrar: la fuente se reconoce por las columnas
python pipeline/run.py                          # ingesta + reconstrucción + controles + exportes + app
python pipeline/run.py --corte "2026-11-30 23:59:59"   # fijar otra fecha de corte
python tests/test_ingesta.py                    # idempotencia, duplicados y correcciones
```

Todo se calcula sobre la base completa, desde `INICIO_OBSERVACION` hasta el corte. El corte es, por
defecto, el último día con datos cargados: cada carga nueva recalcula análisis, insights, segmentos,
audiencias y campañas. Los promedios por día solo usan días completos de cada fuente (`meta.cobertura_dia`).

## Incorporar datos nuevos

1. Copiar los Excel (mensuales o diarios) a `data/raw/`.
2. Ejecutar `python pipeline/run.py` (el corte se mueve solo al último día cargado).
3. Revisar `reports/controles.csv`: debe decir 0 fallas (si hay fallas, el proceso termina con código 1).
4. Tomar las audiencias de `data/exports/audiencias/` y cruzarlas con la lista de supresión
   (consentimiento y autoexclusión) antes de enviar.

Volver a ejecutar no duplica nada: cada archivo se identifica por su SHA-256. Una re-exportación
corregida de un periodo reemplaza a la anterior (ver `docs/02_arquitectura_modelo.md`). Un archivo
diario que empieza después de la 01:00 o termina antes de las 23:00 se marca como recortado.

## Implementado vs. propuesto

| Implementado | Propuesto (requiere decisión, datos o integración) |
|---|---|
| Ingesta idempotente: fuente por columnas, periodo por contenido, hash y manifiesto | Carga diaria automática desde el back office |
| Duplicados exactos y reemplazo de periodos corregidos | Integración con el proveedor SMS (envíos, entregas, clics) |
| Capas stg → core → mart con trazabilidad por archivo y fila | Lista de supresión: autoexclusión, consentimiento, bloqueos |
| Casino integrado en actividad, segmentos y controles | Maestro histórico de jugadores con teléfono |
| Perfil por jugador con 100+ indicadores y corte explícito | Disparadores en tiempo real (registro sin recarga en 24-72 h) |
| 7 segmentos de ciclo de vida, etiquetas y 6 audiencias con control determinístico (20 %) | Tablero conectado a la base |
| Controles de conciliación entre capas y audiencias | Medición del efecto incremental por ola |
| Verificador de codificación y longitud de SMS (GSM-7) | |
| Aplicación Vincero (HTML autocontenido, solo agregados) | |
