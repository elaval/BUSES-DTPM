# Monitor de Flota DTPM - Documentación Técnica

## Descripción General

Sistema automatizado de monitoreo en tiempo real de la flota de buses del Transporte Público Metropolitano de Santiago (DTPM). Captura datos GPS cada 10 minutos, analiza el estado operacional de los buses y genera métricas agregadas por operador y servicio.

## Arquitectura del Sistema

### Componentes Principales

1. **Captura de Datos** ([monitor.py:31-43](scripts/monitor.py#L31-L43))
   - Consulta API oficial DTPM cada 10 minutos
   - Autenticación HTTP Basic
   - Timeout de 30 segundos

2. **Procesamiento** ([monitor.py:46-105](scripts/monitor.py#L46-L105))
   - Parsea formato de datos propietario (delimitado por `;`)
   - Analiza 4 transmisiones GPS por bus (última hora)
   - Clasifica estado operacional: en_movimiento, en_parada, detenido
   - Filtra buses con datos antiguos (>10 min)

3. **Análisis de Métricas** ([monitor.py:108-150](scripts/monitor.py#L108-L150))
   - Agregaciones por operador y servicio
   - Cálculo de porcentajes de actividad
   - Ventana móvil de 1 hora para análisis de tendencias

4. **Almacenamiento**
   - Formato Parquet (columnar, comprimido)
   - Dos archivos:
     - `metricas_historicas.parquet`: Append-only, crecimiento ilimitado
     - `datos_recientes.parquet`: Garbage collection automático (2 horas)

5. **Automatización** ([.github/workflows/monitor.yaml](.github/workflows/monitor.yaml))
   - GitHub Actions con cron cada 10 minutos
   - Commit automático de datos
   - Ejecución manual disponible

## Estructura de Datos

### Datos Raw (datos_recientes.parquet)
```
timestamp              datetime64[ns]  # Momento de captura
patente               string           # Identificador del bus
operador              int64            # ID del operador
servicio              string           # Código del servicio (ej: 210, C16)
sentido               string           # Dirección de la ruta
latitud               float64          # Coordenada GPS
longitud              float64          # Coordenada GPS
velocidad_actual      float64          # km/h en última transmisión
velocidad_max         float64          # km/h máxima en las 4 transmisiones
velocidad_min         float64          # km/h mínima en las 4 transmisiones
velocidad_promedio    float64          # km/h promedio en las 4 transmisiones
estado                string           # en_movimiento | en_parada | detenido
edad_datos_min        float64          # Minutos desde última transmisión GPS
```

### Métricas Agregadas (metricas_historicas.parquet)
```
timestamp              datetime64[ns]
operador               int64
servicio               string (null para nivel operador)
nivel                  string (operador | servicio)
total_buses            int64
buses_en_movimiento    int64
buses_detenidos        int64
pct_en_movimiento      float64
```

## Flujo de Datos

```
API DTPM → Parsing → Clasificación Estado → Agregación → Storage
   ↓                                            ↓
10 min                                    Parquet Files
                                               ↓
                                         Git Commit (GitHub Actions)
```

## Lógica de Clasificación de Estado

El sistema analiza las últimas 4 transmisiones GPS (ventana de ~10 min) para determinar el estado:

- **en_movimiento**: velocidad_max > 5 km/h
- **en_parada**: 0 < velocidad_max ≤ 5 km/h
- **detenido**: velocidad_max = 0 km/h

## Configuración y Despliegue

### Variables de Entorno Requeridas
- `DTPM_USUARIO`: Usuario de la API DTPM
- `DTPM_CLAVE`: Contraseña de la API DTPM

### GitHub Secrets
Configurar en: Settings → Secrets and variables → Actions
- `DTPM_USUARIO`
- `DTPM_CLAVE`

### Permisos de GitHub Actions
Settings → Actions → General → Workflow permissions → **Read and write permissions**

### Dependencias
```
pandas>=2.0.0
pyarrow>=12.0.0
requests>=2.31.0
```

## Análisis de Datos

### Ejemplo 1: Actividad por Operador (Últimas 24h)
```python
import pandas as pd

df = pd.read_parquet('data/metricas_historicas.parquet')

# Filtrar últimas 24 horas
df_24h = df[df['timestamp'] > pd.Timestamp.now() - pd.Timedelta(hours=24)]
df_op = df_24h[df_24h['nivel'] == 'operador']

# Promedio de actividad por operador
actividad = df_op.groupby('operador').agg({
    'total_buses': 'mean',
    'pct_en_movimiento': 'mean'
}).round(1)

print(actividad)
```

### Ejemplo 2: Servicios Más Activos
```python
df_serv = df[df['nivel'] == 'servicio']
df_serv_24h = df_serv[df_serv['timestamp'] > pd.Timestamp.now() - pd.Timedelta(hours=24)]

top_servicios = df_serv_24h.groupby('servicio').agg({
    'total_buses': 'mean',
    'pct_en_movimiento': 'mean'
}).sort_values('total_buses', ascending=False).head(10)

print(top_servicios)
```

### Ejemplo 3: Ventana Móvil - Análisis Horario
```python
df_recientes = pd.read_parquet('data/datos_recientes.parquet')

# Agrupar por hora
df_recientes['hora'] = df_recientes['timestamp'].dt.hour

actividad_horaria = df_recientes.groupby(['hora', 'operador']).agg({
    'patente': 'nunique',  # Buses únicos
    'estado': lambda x: (x == 'en_movimiento').mean() * 100
}).reset_index()

print(actividad_horaria)
```

## Características Técnicas

### Optimizaciones
- **Garbage Collection Automático**: Retiene solo 2h de datos raw ([monitor.py:153-172](scripts/monitor.py#L153-L172))
- **Deduplicación**: Elimina registros duplicados por timestamp+operador+servicio
- **Formato Columnar**: Parquet reduce tamaño ~10x vs CSV
- **Filtrado Temprano**: Descarta buses con datos antiguos antes de procesamiento

### Limitaciones Actuales
- No hay manejo de rate limiting en la API
- Sin retry logic para fallos de red
- Crecimiento ilimitado del histórico (puede crecer indefinidamente)
- Sin alertas o notificaciones
- Sin validación de credenciales antes de ejecución

## Mantenimiento

### Monitoreo del Sistema
```bash
# Ver últimas ejecuciones
gh run list --workflow=monitor.yaml --limit 10

# Ver logs de ejecución específica
gh run view <run_id> --log
```

### Limpieza Manual de Histórico
```python
# Si el archivo crece demasiado, reducir a últimos N días
df = pd.read_parquet('data/metricas_historicas.parquet')
df_filtrado = df[df['timestamp'] > pd.Timestamp.now() - pd.Timedelta(days=90)]
df_filtrado.to_parquet('data/metricas_historicas.parquet', index=False)
```

---

## Siguientes Pasos Sugeridos

### 🔴 Prioridad Alta

1. **Dashboard de Visualización en Tiempo Real**
   - Implementar dashboard web con Streamlit o Plotly Dash
   - Gráficos: actividad por hora, mapa de calor de operadores, series temporales
   - Desplegar en Streamlit Cloud o GitHub Pages (static)

2. **Sistema de Alertas**
   - Alertas cuando operadores caen bajo X% de actividad
   - Notificaciones vía email o Slack
   - Detección de anomalías (caídas abruptas de flota)

3. **Mejoras de Robustez**
   - Implementar retry logic con backoff exponencial
   - Validar credenciales al inicio
   - Manejo de rate limiting (429 errors)
   - Logging estructurado (JSON logs)

### 🟡 Prioridad Media

4. **Análisis Geoespacial**
   - Clustering de posiciones para identificar terminales/zonas de alta actividad
   - Detección de buses "perdidos" (fuera de rutas esperadas)
   - Análisis de cobertura geográfica por servicio

5. **Optimizaciones de Almacenamiento**
   - Particionamiento del histórico por mes/año
   - Compresión adaptativa según antigüedad
   - Migrar histórico antiguo a almacenamiento frío (S3/GCS)

6. **API REST Local**
   - Endpoint para consultar métricas actuales
   - Filtros por operador, servicio, rango temporal
   - Documentación con OpenAPI/Swagger

### 🟢 Prioridad Baja

7. **Machine Learning Predictivo**
   - Predicción de demanda por servicio/hora
   - Detección de patrones anómalos en rutas
   - Forecast de disponibilidad de flota

8. **Integración con Otros Datos**
   - Cruzar con datos de clima (correlación lluvia vs actividad)
   - Datos de eventos (partidos, conciertos) vs demanda
   - Datos de tráfico urbano

9. **Testing y CI/CD**
   - Tests unitarios para parsing y agregaciones
   - Tests de integración con mock de API
   - Pre-commit hooks para validación

---

## Recursos Útiles

- **API DTPM**: http://www.dtpmetropolitano.cl/posiciones
- **Pandas Parquet**: https://pandas.pydata.org/docs/reference/api/pandas.read_parquet.html
- **GitHub Actions Cron**: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule
- **Streamlit**: https://streamlit.io/ (para dashboard)

---

*Documentación generada: 2026-05-08*
