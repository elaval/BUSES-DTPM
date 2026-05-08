"""
Monitor de flota de buses DTPM
Captura datos cada 10 minutos y genera métricas agregadas
"""

import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timedelta
import os
from pathlib import Path

# Cargar variables de entorno desde .env (solo en ambiente local)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv no está instalado (ej: GitHub Actions)

# Configuración
USUARIO = os.getenv('DTPM_USUARIO')
CLAVE = os.getenv('DTPM_CLAVE')
API_URL = "http://www.dtpmetropolitano.cl/posiciones"

DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

ARCHIVO_HISTORICO = DATA_DIR / 'metricas_historicas.parquet'
ARCHIVO_RECIENTES = DATA_DIR / 'datos_recientes.parquet'

# Constantes
VENTANA_HORAS = 1  # Ventana móvil de análisis
RETENER_HORAS = 168  # Retener datos raw últimos 7 días (168 horas)


def capturar_datos_api():
    """Captura datos de la API del DTPM"""
    try:
        response = requests.get(
            API_URL,
            auth=HTTPBasicAuth(USUARIO, CLAVE),
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error capturando datos: {e}")
        return None


def parsear_posiciones(data):
    """
    Parsea los datos de la API y analiza actividad de cada bus
    Retorna DataFrame con un registro por bus (última transmisión + análisis)
    """
    fecha_consulta = datetime.strptime(data['fecha_consulta'], '%Y%m%d%H%M%S')
    registros = []
    
    for posicion_string in data['posiciones']:
        campos = posicion_string.split(';')
        
        # Analizar las 4 transmisiones para determinar actividad
        velocidades = []
        for i in range(0, min(len(campos), 48), 12):
            if i + 4 < len(campos) and campos[i+4]:
                try:
                    velocidades.append(float(campos[i+4]))
                except ValueError:
                    continue
        
        if not velocidades or len(campos) < 12:
            continue
        
        try:
            # Datos de la transmisión más reciente
            fecha_gps = datetime.strptime(campos[0], '%d-%m-%Y %H:%M:%S')
            edad_min = (fecha_consulta - fecha_gps).total_seconds() / 60
            
            # Solo considerar buses con datos recientes (< 10 min)
            if edad_min > 10:
                continue
            
            # Determinar estado operacional
            max_velocidad = max(velocidades)
            if max_velocidad > 5:
                estado = 'en_movimiento'
            elif max_velocidad > 0:
                estado = 'en_parada'
            else:
                estado = 'detenido'
            
            registro = {
                'timestamp': fecha_consulta,
                'patente': campos[1],
                'operador': int(float(campos[6])),
                'servicio': campos[7],
                'sentido': campos[8],
                'latitud': float(campos[2]),
                'longitud': float(campos[3]),
                'velocidad_actual': velocidades[0],
                'velocidad_max_ventana': max_velocidad,
                'estado': estado,
                'edad_datos_min': edad_min
            }
            registros.append(registro)
            
        except (ValueError, IndexError) as e:
            continue
    
    return pd.DataFrame(registros) if registros else pd.DataFrame()


def calcular_metricas(df):
    """
    Calcula métricas agregadas por operador y servicio
    """
    if df.empty:
        return pd.DataFrame()
    
    timestamp = df['timestamp'].iloc[0]
    
    # Métricas por operador
    metricas_operador = df.groupby('operador').agg({
        'patente': 'count',
        'estado': lambda x: (x == 'en_movimiento').sum()
    }).reset_index()
    metricas_operador.columns = ['operador', 'total_buses', 'buses_en_movimiento']
    metricas_operador['buses_detenidos'] = (
        metricas_operador['total_buses'] - metricas_operador['buses_en_movimiento']
    )
    metricas_operador['timestamp'] = timestamp
    metricas_operador['nivel'] = 'operador'
    metricas_operador['servicio'] = None
    
    # Métricas por servicio
    metricas_servicio = df.groupby(['operador', 'servicio']).agg({
        'patente': 'count',
        'estado': lambda x: (x == 'en_movimiento').sum()
    }).reset_index()
    metricas_servicio.columns = ['operador', 'servicio', 'total_buses', 'buses_en_movimiento']
    metricas_servicio['buses_detenidos'] = (
        metricas_servicio['total_buses'] - metricas_servicio['buses_en_movimiento']
    )
    metricas_servicio['timestamp'] = timestamp
    metricas_servicio['nivel'] = 'servicio'
    
    # Combinar
    metricas = pd.concat([metricas_operador, metricas_servicio], ignore_index=True)
    
    # Calcular porcentajes
    metricas['pct_en_movimiento'] = (
        metricas['buses_en_movimiento'] / metricas['total_buses'] * 100
    ).round(1)
    
    return metricas


def guardar_datos_recientes(df_nuevo):
    """
    Guarda datos recientes con garbage collection (últimos 7 días)
    """
    # Leer datos existentes si existen
    if ARCHIVO_RECIENTES.exists():
        df_existente = pd.read_parquet(ARCHIVO_RECIENTES)
        df_combined = pd.concat([df_existente, df_nuevo], ignore_index=True)
    else:
        df_combined = df_nuevo

    # Garbage collection: eliminar datos > 7 días
    # Usar el timestamp más reciente como referencia en lugar de datetime.now()
    # para evitar problemas con zonas horarias
    if not df_combined.empty:
        timestamp_referencia = df_combined['timestamp'].max()
        limite_tiempo = timestamp_referencia - timedelta(hours=RETENER_HORAS)
        df_combined = df_combined[df_combined['timestamp'] >= limite_tiempo]

    # Guardar
    df_combined.to_parquet(ARCHIVO_RECIENTES, index=False)

    return len(df_combined)


def guardar_metricas_historicas(metricas_nuevas):
    """
    Agrega métricas al histórico (append-only)
    """
    if ARCHIVO_HISTORICO.exists():
        df_existente = pd.read_parquet(ARCHIVO_HISTORICO)
        df_combined = pd.concat([df_existente, metricas_nuevas], ignore_index=True)
    else:
        df_combined = metricas_nuevas
    
    # Eliminar duplicados por timestamp + operador + servicio
    df_combined = df_combined.drop_duplicates(
        subset=['timestamp', 'operador', 'nivel', 'servicio'],
        keep='last'
    )
    
    # Guardar
    df_combined.to_parquet(ARCHIVO_HISTORICO, index=False)
    
    return len(df_combined)


def analizar_ventana_movil():
    """
    Analiza la última hora de datos para calcular actividad promedio
    """
    if not ARCHIVO_RECIENTES.exists():
        return None

    df = pd.read_parquet(ARCHIVO_RECIENTES)

    if df.empty:
        return None

    # Filtrar última hora usando el timestamp más reciente como referencia
    timestamp_referencia = df['timestamp'].max()
    limite_tiempo = timestamp_referencia - timedelta(hours=VENTANA_HORAS)
    df_ventana = df[df['timestamp'] >= limite_tiempo]

    if df_ventana.empty:
        return None
    
    # Análisis de actividad en la ventana
    analisis = df_ventana.groupby(['operador', 'patente']).agg({
        'estado': lambda x: 'activo' if (x == 'en_movimiento').any() else 'inactivo',
        'timestamp': 'count'
    }).reset_index()
    
    # Resumir por operador
    resumen = analisis.groupby('operador').agg({
        'patente': 'count',
        'estado': lambda x: (x == 'activo').sum()
    }).reset_index()
    resumen.columns = ['operador', 'buses_unicos', 'buses_activos_ventana']
    
    return resumen


def generar_reporte():
    """
    Genera reporte de la ejecución actual
    """
    print(f"\n{'='*70}")
    print(f"🚌 MONITOR DTPM - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    
    # Capturar datos
    print("\n📡 Capturando datos de la API...")
    data = capturar_datos_api()
    
    if not data:
        print("❌ No se pudieron capturar datos")
        return False
    
    # Parsear
    print("📊 Parseando posiciones...")
    df_buses = parsear_posiciones(data)
    
    if df_buses.empty:
        print("⚠️  No hay buses con datos recientes")
        return False
    
    print(f"✅ {len(df_buses)} buses procesados")
    
    # Calcular métricas
    print("📈 Calculando métricas...")
    metricas = calcular_metricas(df_buses)
    
    # Guardar datos
    print("💾 Guardando datos...")
    n_recientes = guardar_datos_recientes(df_buses)
    n_historico = guardar_metricas_historicas(metricas)

    dias_retencion = RETENER_HORAS / 24
    print(f"   - Datos recientes: {n_recientes} registros (últimos {dias_retencion:.0f} días)")
    print(f"   - Histórico métricas: {n_historico} registros totales")
    
    # Análisis ventana móvil
    print(f"\n🔍 Análisis ventana móvil (última {VENTANA_HORAS}h):")
    resumen = analizar_ventana_movil()
    
    if resumen is not None and not resumen.empty:
        print(resumen.to_string(index=False))
    
    # Mostrar métricas actuales
    print("\n📊 Métricas actuales por operador:")
    metricas_op = metricas[metricas['nivel'] == 'operador'][
        ['operador', 'total_buses', 'buses_en_movimiento', 'pct_en_movimiento']
    ].sort_values('total_buses', ascending=False)
    print(metricas_op.to_string(index=False))
    
    print("\n✅ Ejecución completada\n")
    return True


if __name__ == "__main__":
    generar_reporte()
