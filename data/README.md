# Datos del Monitor de Flota DTPM

Esta rama (`data`) la genera **automáticamente** GitHub Actions en cada captura
(cada ~10 minutos). Contiene solo la versión más reciente de los datos, en un
único commit sin historial, para que el repositorio no crezca. El código está en
la rama [`main`](https://github.com/elaval/BUSES-DTPM/tree/main).

La rama también sirve el dashboard en GitHub Pages:
<https://elaval.github.io/BUSES-DTPM/>

> No edites archivos en esta rama: se reescribe completa en cada captura.
> Este README se mantiene en `main`, en `data/README.md`.

## Archivos

| Archivo | Qué contiene | Tamaño aprox. | Se actualiza |
|---|---|---|---|
| `data/metricas_historicas.parquet` | Conteos agregados por operador y por servicio, una fila por captura | 3 MB | Cada captura (crece) |
| `data/datos_recientes.parquet` | Un registro por bus y captura, con posición y velocidad. Solo los últimos 7 días | 5–15 MB | Cada captura (ventana móvil) |
| `data_vivo.json` | Resumen liviano para el dashboard (últimos 7 días) | 5 KB | Cada captura |
| `data_estatico.json` | Velocidad por tramo entre paraderos (toda la red), comunas y tramos más lentos (análisis may–nov 2026) | 400 KB | Manual (`scripts/analisis_paraderos.py`) |
| `lineas.json` | Análisis por recorrido: buses por hora, paraderos y velocidad por tramo; índice paradero → recorridos | 6 MB | Manual (`scripts/analisis_paraderos.py`) |
| `index.html` | Página del dashboard | — | Con cada cambio en `main` |

Además, el detalle bus por bus de **todas las capturas del 8 de mayo al 14 de
noviembre de 2026** (9,3 millones de registros, rescatados del historial antiguo)
está como archivo descargable en el Release
[`archivo-gps-2026-11`](https://github.com/elaval/BUSES-DTPM/releases/tag/archivo-gps-2026-11).
Tiene las mismas columnas que `datos_recientes.parquet`, sin `senal_reciente`
(ver notas de calidad).

## Cómo leerlos

```python
import pandas as pd

BASE = "https://raw.githubusercontent.com/elaval/BUSES-DTPM/data/data/"
metricas = pd.read_parquet(BASE + "metricas_historicas.parquet")
recientes = pd.read_parquet(BASE + "datos_recientes.parquet")
```

Los nombres de los operadores están en la rama `main`:
<https://raw.githubusercontent.com/elaval/BUSES-DTPM/main/data/operadores.json>

---

## `data/metricas_historicas.parquet`

Una fila por **captura × operador** (`nivel = "operador"`) y por **captura ×
operador × servicio** (`nivel = "servicio"`). Desde el 8 de mayo de 2026.

| Columna | Tipo | Descripción |
|---|---|---|
| `timestamp` | datetime | Momento de la captura, **hora de Chile** (America/Santiago), sin zona horaria |
| `nivel` | texto | `operador` o `servicio` |
| `operador` | entero | ID de la unidad de negocio. Nombre en `operadores.json` (p. ej. `5` = U5 Metropolitana, `32` = U8 Alfa) |
| `servicio` | texto | Código interno del servicio en la API (p. ej. `T506`, `T1998`, `T930 C0`). Vacío cuando `nivel = "operador"` |
| `total_buses` | entero | Buses con GPS de hace 190 minutos o menos |
| `buses_en_movimiento` | entero | Buses con velocidad máxima mayor a 5 km/h en sus últimas 4 transmisiones |
| `buses_detenidos` | entero | `total_buses − buses_en_movimiento`. Incluye a los buses sin señal reciente (se mantiene así por comparabilidad histórica) |
| `pct_en_movimiento` | decimal | `buses_en_movimiento / total_buses × 100` |
| `buses_sin_senal` | decimal | Buses con último GPS de hace 10 a 190 minutos y **no** en movimiento. **Vacío antes del 15-nov-2026** (la métrica no existía) |
| `buses_operando` | decimal | Buses **operando**: GPS al día y se movieron en la captura actual o en alguna de las 2 anteriores (~20 min). Incluye a los detenidos en paradero o semáforo; excluye a los encendidos en un terminal sin salir. **Vacío antes del 15-nov-2026** |
| `buses_operando_comercial` | decimal | Parte de `buses_operando` con servicio comercial (código de servicio que no termina en `TS`). **Vacío antes del 15-nov-2026** |

Muestra (`nivel = "operador"`):

| timestamp | nivel | operador | servicio | total_buses | buses_en_movimiento | buses_detenidos | pct_en_movimiento | buses_sin_senal |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 2026-11-15 09:30:02 | operador | 40 | | 325 | 127 | 198 | 39.1 | 13 |
| 2026-11-15 09:30:02 | operador | 41 | | 290 | 131 | 159 | 45.2 | 67 |
| 2026-11-15 09:30:02 | operador | 42 | | 331 | 136 | 195 | 41.1 | 59 |

Muestra (`nivel = "servicio"`):

| timestamp | nivel | operador | servicio | total_buses | buses_en_movimiento | buses_detenidos | pct_en_movimiento | buses_sin_senal |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 2026-11-15 09:30:02 | servicio | 42 | T1997 | 2 | 2 | 0 | 100.0 | 0 |
| 2026-11-15 09:30:02 | servicio | 42 | T1998 | 11 | 9 | 2 | 81.8 | 0 |
| 2026-11-15 09:30:02 | servicio | 42 | T19TS | 104 | 8 | 96 | 7.7 | 38 |

---

## `data/datos_recientes.parquet`

Un registro por **bus × captura**. Solo los **últimos 7 días** (las filas más
antiguas se eliminan en cada captura). Para meses anteriores, usa el archivo del
Release.

| Columna | Tipo | Descripción |
|---|---|---|
| `timestamp` | datetime | Momento de la captura, hora de Chile |
| `patente` | texto | Patente del bus (p. ej. `VRZJ-42`) |
| `operador` | entero | ID de la unidad de negocio (ver `operadores.json`) |
| `servicio` | texto | Código interno del servicio en la API. Los que terminan en `TS` (p. ej. `T3TS`) agrupan buses **sin servicio comercial asignado**: según nuestra lectura, buses en tránsito hacia o desde terminales |
| `sentido` | texto | `I` (ida) o `R` (regreso) |
| `latitud`, `longitud` | decimal | Posición de la última transmisión GPS (WGS84) |
| `velocidad_actual` | decimal | km/h en la última transmisión |
| `velocidad_max` | decimal | km/h máxima entre las últimas 4 transmisiones |
| `velocidad_min` | decimal | km/h mínima entre las últimas 4 transmisiones |
| `velocidad_promedio` | decimal | km/h promedio de las últimas 4 transmisiones |
| `estado` | texto | `en_movimiento` (`velocidad_max` > 5), `en_parada` (0 < `velocidad_max` ≤ 5) o `detenido` (`velocidad_max` = 0) |
| `edad_datos_min` | decimal | Minutos entre la última transmisión GPS y la captura (0 a 190) |
| `senal_reciente` | booleano | `True` si `edad_datos_min` ≤ 10. **Vacío en filas anteriores al 15-nov-2026** |
| `se_movio` | booleano | GPS al día y, en esta captura, `velocidad_max` > 5 km/h o desplazamiento > 150 m respecto de la captura anterior. **Vacío en filas anteriores al 15-nov-2026** |
| `operando` | booleano | `se_movio` en esta captura o en alguna de las 2 anteriores (dentro de 25 min). **Vacío en filas anteriores al 15-nov-2026** |
| `comercial` | booleano | `True` si el código de servicio no termina en `TS`. **Vacío en filas anteriores al 15-nov-2026** |

Muestra:

| timestamp | patente | operador | servicio | sentido | latitud | longitud | velocidad_actual | estado | edad_datos_min | velocidad_max | velocidad_min | velocidad_promedio | senal_reciente |
|---|---|---:|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| 2026-11-15 09:30:02 | VPTC-86 | 16 | T3TS | I | -33.5116 | -70.8058 | 0.0 | detenido | 0.4 | 0.0 | 0 | 0.0 | True |
| 2026-11-15 09:30:02 | VRZJ-42 | 5 | T506 | I | -33.5198 | -70.7953 | 31.7 | en_movimiento | 0.1 | 31.7 | 0 | 16.8 | True |
| 2026-11-15 09:30:02 | VPTG-61 | 16 | T324 | I | -33.5376 | -70.6994 | 0.0 | en_parada | 5.0 | 1.1 | 0 | 0.3 | True |

### Del código `servicio` al número de recorrido público

La API usa códigos internos (`T506`). Para llegar al recorrido que ve el público
(`506`) se usa el archivo oficial del DTPM `Servicios_decos_09022026.xlsx`: la
columna `CODIGO_RUTA` sin su última parte (`T506 00I` → `T506`) corresponde a
`servicio`, y `CODIGO_USUARIO` es el recorrido público. Cubre ~94 % de los
registros. Algunas variantes (p. ej. `T506e1`) no aparecen en ese archivo.

---

## Clasificación de cada bus

| Categoría | Criterio |
|---|---|
| En movimiento | `velocidad_max` > 5 km/h |
| Detenido | `velocidad_max` ≤ 5 km/h y GPS de hace 10 minutos o menos (incluye `en_parada` y `detenido`) |
| Sin señal reciente | Último GPS de hace más de 10 y hasta 190 minutos, y no en movimiento |
| Excluido | Último GPS de hace más de 190 minutos. No se guarda: la API también lista buses sin transmitir hace días |
| **Operando** | GPS al día y se movió (> 5 km/h o > 150 m) en los últimos ~20 min. Transversal a las anteriores: un bus detenido en un paradero puede estar operando |

### Servicios "TS" (sin servicio comercial)

Cada unidad de negocio tiene un código `T<unidad>TS` (p. ej. `T5TS`, `T19TS`). No
figura en el archivo oficial de servicios ni en el GTFS. Los datos muestran que los
buses pasan de `TS` a un recorrido al empezar su servicio (sobre todo entre 5 y 7 h)
y vuelven a `TS` al terminarlo, y que de noche ~40 % de los buses con señal tiene
este código. Lo interpretamos como **bus sin recorrido asignado**: traslados entre el
depósito y el inicio o fin de su recorrido, o equipo encendido fuera de servicio. El
DTPM no publica una definición oficial.

---

## Notas de calidad

- **Frecuencia de captura.** Hasta el 14-nov-2026 el cron de GitHub corría solo
  ~4 veces al día, a horas irregulares, y hay huecos (p. ej. del 6 al 29 de
  julio). Desde el 15-nov-2026 hay una captura cada 10 minutos, disparada por
  cron-job.org.
- **Zona horaria del GPS (corregida el 15-nov-2026).** Antes de esa fecha,
  `edad_datos_min` está desfasada: la hora del GPS viene en UTC y se restaba sin
  convertir. Para obtener la antigüedad real hay que **sumar 180 minutos** en
  horario de verano (UTC−3) o **240** en invierno (UTC−4). Esto aplica también al
  archivo del Release.
- **Umbral de 190 minutos.** Por ese mismo desfase, el filtro antiguo de "más de
  10 minutos" descartaba en la práctica los GPS de más de ~190 minutos. El
  umbral actual reproduce ese comportamiento para que `total_buses` siga siendo
  comparable con el histórico.
- **Nombres de operadores (corregidos el 15-nov-2026).** Antes, `operadores.json`
  tenía nombres antiguos del Transantiago (p. ej. "STP Santiago" para el ID 32,
  que en realidad es Buses Alfa). Los IDs nunca cambiaron: basta con usar el
  `operadores.json` actual.
- **Crisis de Metropol (sep–nov 2026).** Buses Alfa (ID 32) y Buses Omega (ID 33)
  reducen su flota desde septiembre hasta casi desaparecer en noviembre, por la
  reorganización y posterior liquidación del grupo Metropol. Sus recorridos los
  cubren otros operadores con códigos de servicio nuevos.
- **Columnas en el archivo del Release.** En el 0,5 % de las capturas más
  antiguas, la velocidad máxima viene en una columna llamada
  `velocidad_max_ventana`.
