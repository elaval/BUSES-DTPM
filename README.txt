# Monitor de Flota DTPM

Sistema automatizado de monitoreo de buses del Transporte Público Metropolitano de Santiago.

## Características

- 📡 Captura datos cada 10 minutos vía API oficial del DTPM
- 📊 Calcula métricas agregadas por operador y servicio
- 🔄 Ventana móvil de 1 hora para análisis de actividad
- 🗑️ Garbage collection automático (retiene solo últimas 2 horas de datos raw)
- 💾 Almacenamiento eficiente en formato Parquet
- ⚡ Ejecución automatizada con GitHub Actions

## Estructura de datos

### `data/metricas_historicas.parquet`
Métricas agregadas históricas:
- `timestamp`: Momento de la captura
- `operador`: ID del operador
- `servicio`: Código del servicio (null para métricas de operador)
- `nivel`: 'operador' o 'servicio'
- `total_buses`: Total de buses detectados
- `buses_en_movimiento`: Buses con velocidad > 5 km/h
- `buses_detenidos`: Buses detenidos o en parada
- `pct_en_movimiento`: Porcentaje de buses activos

### `data/datos_recientes.parquet`
Datos raw de últimas 2 horas (para análisis de ventana móvil)

## Configuración

### Desarrollo Local

1. Crear entorno virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Configurar credenciales en archivo `.env`:
   ```bash
   DTPM_USUARIO=tu_usuario
   DTPM_CLAVE=tu_clave
   ```

3. Ejecutar captura manual:
   ```bash
   python scripts/monitor.py
   ```

4. Ver dashboard:
   ```bash
   streamlit run dashboard.py
   # Abre http://localhost:8501
   ```

### Despliegue en GitHub

Ver instrucciones detalladas en [SETUP_GITHUB.md](SETUP_GITHUB.md)

**Resumen**:
1. Agregar secrets en GitHub:
   - `DTPM_USUARIO`: Usuario de la API
   - `DTPM_CLAVE`: Contraseña de la API

2. Habilitar permisos de escritura para GitHub Actions:
   Settings → Actions → General → Workflow permissions → Read and write permissions

## Análisis

```python
import pandas as pd

# Leer histórico
df = pd.read_parquet('data/metricas_historicas.parquet')

# Métricas por operador en las últimas 24 horas
df_24h = df[df['timestamp'] > pd.Timestamp.now() - pd.Timedelta(hours=24)]
df_operadores = df_24h[df_24h['nivel'] == 'operador']

# Promedio de buses en movimiento por operador
promedio = df_operadores.groupby('operador')['buses_en_movimiento'].mean()
