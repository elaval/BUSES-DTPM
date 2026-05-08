"""
Dashboard de Monitoreo de Flota DTPM
Visualización en tiempo real de métricas de buses
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path

# Configuración de página
st.set_page_config(
    page_title="Monitor Flota DTPM",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Paths
DATA_DIR = Path('data')
ARCHIVO_HISTORICO = DATA_DIR / 'metricas_historicas.parquet'
ARCHIVO_RECIENTES = DATA_DIR / 'datos_recientes.parquet'

# Mapeo de operadores (puedes completar con nombres reales)
OPERADORES = {
    2: "Express",
    4: "Subus Chile",
    5: "Metbus",
    16: "Redbus Urbano",
    32: "STP Santiago",
    33: "Buses Vule",
    34: "Alsacia",
    35: "Unitran",
    36: "Mall Martínez",
    37: "Gran Santiago",
    38: "Buses Gran Santiago",
    39: "Turbus",
    40: "Inversiones Alsacia",
    41: "Comercial Nuevo Milenio",
    42: "Express de Santiago Uno"
}

@st.cache_data(ttl=60)
def cargar_metricas_historicas():
    """Carga métricas históricas con cache de 60 segundos"""
    if not ARCHIVO_HISTORICO.exists():
        return pd.DataFrame()
    df = pd.read_parquet(ARCHIVO_HISTORICO)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

@st.cache_data(ttl=60)
def cargar_datos_recientes():
    """Carga datos recientes con cache de 60 segundos"""
    if not ARCHIVO_RECIENTES.exists():
        return pd.DataFrame()
    df = pd.read_parquet(ARCHIVO_RECIENTES)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def main():
    # Header
    st.title("🚌 Monitor de Flota DTPM Santiago")
    st.markdown("Sistema de monitoreo en tiempo real del Transporte Público Metropolitano")

    # Cargar datos
    df_metricas = cargar_metricas_historicas()
    df_recientes = cargar_datos_recientes()

    if df_metricas.empty:
        st.warning("⚠️ No hay datos históricos disponibles. Ejecuta `python scripts/monitor.py` primero.")
        return

    # Sidebar - Filtros
    st.sidebar.header("⚙️ Filtros")

    # Rango de tiempo
    tiempo_opciones = {
        "Última hora": 1,
        "Últimas 3 horas": 3,
        "Últimas 6 horas": 6,
        "Últimas 12 horas": 12,
        "Últimas 24 horas": 24,
        "Últimos 3 días": 72,
        "Última semana": 168
    }
    tiempo_seleccionado = st.sidebar.selectbox(
        "Período de tiempo",
        options=list(tiempo_opciones.keys()),
        index=4
    )
    horas = tiempo_opciones[tiempo_seleccionado]

    # Filtrar datos por tiempo
    limite_tiempo = datetime.now() - timedelta(hours=horas)
    df_filtrado = df_metricas[df_metricas['timestamp'] >= limite_tiempo].copy()

    if df_filtrado.empty:
        st.warning(f"⚠️ No hay datos para el período seleccionado ({tiempo_seleccionado})")
        return

    # Operadores disponibles
    operadores_disponibles = sorted(df_filtrado['operador'].unique())
    operadores_nombres = [f"{op} - {OPERADORES.get(op, 'Desconocido')}" for op in operadores_disponibles]

    operador_seleccionado = st.sidebar.multiselect(
        "Operadores",
        options=operadores_nombres,
        default=operadores_nombres[:5]
    )

    # Extraer IDs de operadores seleccionados
    if operador_seleccionado:
        operadores_ids = [int(op.split(' - ')[0]) for op in operador_seleccionado]
        df_filtrado = df_filtrado[df_filtrado['operador'].isin(operadores_ids)]

    # Botón de actualización
    if st.sidebar.button("🔄 Actualizar datos"):
        st.cache_data.clear()
        st.rerun()

    # Información de última actualización
    ultima_actualizacion = df_metricas['timestamp'].max()
    tiempo_transcurrido = datetime.now() - ultima_actualizacion
    minutos = int(tiempo_transcurrido.total_seconds() / 60)
    st.sidebar.info(f"📅 Última actualización: hace {minutos} min")

    # === MÉTRICAS PRINCIPALES ===
    st.header("📊 Métricas Actuales")

    # Obtener datos más recientes por operador
    df_ultimo = df_filtrado[df_filtrado['nivel'] == 'operador'].sort_values('timestamp').groupby('operador').tail(1)

    if not df_ultimo.empty:
        col1, col2, col3, col4 = st.columns(4)

        total_buses = df_ultimo['total_buses'].sum()
        buses_en_movimiento = df_ultimo['buses_en_movimiento'].sum()
        buses_detenidos = df_ultimo['buses_detenidos'].sum()
        pct_activo = (buses_en_movimiento / total_buses * 100) if total_buses > 0 else 0

        col1.metric("Total Buses", f"{total_buses:,}")
        col2.metric("En Movimiento", f"{buses_en_movimiento:,}", f"{pct_activo:.1f}%")
        col3.metric("Detenidos", f"{buses_detenidos:,}")
        col4.metric("Operadores", len(df_ultimo))

    # === GRÁFICOS PRINCIPALES ===

    # Fila 1: Serie temporal y distribución
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Evolución Temporal de Flota Activa")
        df_operador = df_filtrado[df_filtrado['nivel'] == 'operador'].copy()
        df_operador['operador_nombre'] = df_operador['operador'].map(
            lambda x: f"{x} - {OPERADORES.get(x, 'Desconocido')}"
        )

        fig_temporal = px.line(
            df_operador,
            x='timestamp',
            y='buses_en_movimiento',
            color='operador_nombre',
            title='Buses en movimiento por operador',
            labels={
                'buses_en_movimiento': 'Buses en movimiento',
                'timestamp': 'Fecha/Hora',
                'operador_nombre': 'Operador'
            }
        )
        fig_temporal.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_temporal, use_container_width=True)

    with col2:
        st.subheader("📊 Distribución Actual por Operador")
        df_barras = df_ultimo.copy()
        df_barras['operador_nombre'] = df_barras['operador'].map(
            lambda x: f"{x} - {OPERADORES.get(x, 'Desconocido')}"
        )
        df_barras = df_barras.sort_values('total_buses', ascending=True)

        fig_barras = go.Figure()
        fig_barras.add_trace(go.Bar(
            y=df_barras['operador_nombre'],
            x=df_barras['buses_en_movimiento'],
            name='En movimiento',
            orientation='h',
            marker=dict(color='#2ecc71')
        ))
        fig_barras.add_trace(go.Bar(
            y=df_barras['operador_nombre'],
            x=df_barras['buses_detenidos'],
            name='Detenidos',
            orientation='h',
            marker=dict(color='#e74c3c')
        ))
        fig_barras.update_layout(
            barmode='stack',
            height=400,
            title='Flota actual por operador',
            xaxis_title='Número de buses',
            yaxis_title='Operador',
            legend=dict(orientation='h', y=1.1, x=0.5, xanchor='center')
        )
        st.plotly_chart(fig_barras, use_container_width=True)

    # Fila 2: Porcentaje de actividad y mapa de calor
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📉 % de Flota Activa en el Tiempo")
        fig_pct = px.line(
            df_operador,
            x='timestamp',
            y='pct_en_movimiento',
            color='operador_nombre',
            title='Porcentaje de buses en movimiento',
            labels={
                'pct_en_movimiento': '% Activo',
                'timestamp': 'Fecha/Hora',
                'operador_nombre': 'Operador'
            }
        )
        fig_pct.update_layout(height=400, hovermode='x unified')
        fig_pct.add_hline(y=50, line_dash="dash", line_color="gray",
                         annotation_text="50%", annotation_position="right")
        st.plotly_chart(fig_pct, use_container_width=True)

    with col2:
        st.subheader("🔥 Mapa de Calor - Actividad por Hora")
        df_operador['hora'] = df_operador['timestamp'].dt.hour
        df_operador['dia'] = df_operador['timestamp'].dt.date

        # Crear pivote para heatmap
        pivot_data = df_operador.pivot_table(
            values='pct_en_movimiento',
            index='operador_nombre',
            columns='hora',
            aggfunc='mean'
        )

        if not pivot_data.empty:
            fig_heatmap = px.imshow(
                pivot_data,
                labels=dict(x="Hora del día", y="Operador", color="% Activo"),
                x=[f"{h:02d}:00" for h in pivot_data.columns],
                y=pivot_data.index,
                color_continuous_scale='RdYlGn',
                aspect='auto'
            )
            fig_heatmap.update_layout(height=400)
            st.plotly_chart(fig_heatmap, use_container_width=True)

    # === ANÁLISIS DE SERVICIOS ===
    st.header("🚏 Análisis por Servicio")

    df_servicios = df_filtrado[df_filtrado['nivel'] == 'servicio'].copy()

    if not df_servicios.empty:
        # Top servicios más activos
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🏆 Top 15 Servicios Más Activos")
            df_top_servicios = df_servicios.sort_values('timestamp').groupby('servicio').tail(1)
            df_top_servicios = df_top_servicios.nlargest(15, 'total_buses')

            fig_top = px.bar(
                df_top_servicios,
                x='servicio',
                y='total_buses',
                color='pct_en_movimiento',
                title='Servicios con mayor flota',
                labels={
                    'servicio': 'Servicio',
                    'total_buses': 'Total Buses',
                    'pct_en_movimiento': '% Activo'
                },
                color_continuous_scale='Viridis'
            )
            fig_top.update_layout(height=400)
            st.plotly_chart(fig_top, use_container_width=True)

        with col2:
            st.subheader("⚡ Servicios Más Eficientes")
            df_eficientes = df_servicios[df_servicios['total_buses'] >= 5]  # Mínimo 5 buses
            df_eficientes = df_eficientes.sort_values('timestamp').groupby('servicio').tail(1)
            df_eficientes = df_eficientes.nlargest(15, 'pct_en_movimiento')

            fig_eficientes = px.bar(
                df_eficientes,
                x='servicio',
                y='pct_en_movimiento',
                color='total_buses',
                title='Servicios con mayor % de actividad',
                labels={
                    'servicio': 'Servicio',
                    'pct_en_movimiento': '% Activo',
                    'total_buses': 'Total Buses'
                },
                color_continuous_scale='Blues'
            )
            fig_eficientes.update_layout(height=400)
            st.plotly_chart(fig_eficientes, use_container_width=True)

    # === TABLA DE DATOS ===
    st.header("📋 Datos Detallados")

    tab1, tab2 = st.tabs(["Operadores", "Servicios"])

    with tab1:
        st.subheader("Métricas por Operador (Última medición)")
        df_tabla_op = df_ultimo.copy()
        df_tabla_op['operador_nombre'] = df_tabla_op['operador'].map(
            lambda x: f"{x} - {OPERADORES.get(x, 'Desconocido')}"
        )
        df_tabla_op = df_tabla_op[[
            'operador_nombre', 'total_buses', 'buses_en_movimiento',
            'buses_detenidos', 'pct_en_movimiento', 'timestamp'
        ]].sort_values('total_buses', ascending=False)

        df_tabla_op.columns = [
            'Operador', 'Total Buses', 'En Movimiento',
            'Detenidos', '% Activo', 'Timestamp'
        ]

        st.dataframe(
            df_tabla_op,
            use_container_width=True,
            hide_index=True
        )

    with tab2:
        if not df_servicios.empty:
            st.subheader("Métricas por Servicio (Última medición)")
            df_tabla_serv = df_servicios.sort_values('timestamp').groupby('servicio').tail(1)
            df_tabla_serv['operador_nombre'] = df_tabla_serv['operador'].map(
                lambda x: OPERADORES.get(x, f"Op {x}")
            )
            df_tabla_serv = df_tabla_serv[[
                'servicio', 'operador_nombre', 'total_buses',
                'buses_en_movimiento', 'buses_detenidos',
                'pct_en_movimiento', 'timestamp'
            ]].sort_values('total_buses', ascending=False)

            df_tabla_serv.columns = [
                'Servicio', 'Operador', 'Total Buses', 'En Movimiento',
                'Detenidos', '% Activo', 'Timestamp'
            ]

            st.dataframe(
                df_tabla_serv,
                use_container_width=True,
                hide_index=True
            )

    # === MAPA (si hay datos recientes con coordenadas) ===
    if not df_recientes.empty:
        st.header("🗺️ Mapa de Posiciones en Tiempo Real")

        # Filtrar últimos datos
        df_mapa = df_recientes[df_recientes['timestamp'] >= datetime.now() - timedelta(minutes=15)].copy()

        if not df_mapa.empty:
            # Muestra máximo 1000 buses para no saturar
            if len(df_mapa) > 1000:
                df_mapa = df_mapa.sample(1000)

            df_mapa['operador_nombre'] = df_mapa['operador'].map(
                lambda x: OPERADORES.get(x, f"Operador {x}")
            )

            # Color por estado
            color_map = {
                'en_movimiento': '#2ecc71',
                'en_parada': '#f39c12',
                'detenido': '#e74c3c'
            }
            df_mapa['color'] = df_mapa['estado'].map(color_map)

            fig_mapa = px.scatter_mapbox(
                df_mapa,
                lat='latitud',
                lon='longitud',
                color='estado',
                hover_data=['patente', 'servicio', 'operador_nombre', 'velocidad_actual'],
                color_discrete_map=color_map,
                zoom=10,
                height=600,
                title=f"Posiciones de buses (últimos 15 min) - {len(df_mapa)} buses"
            )

            fig_mapa.update_layout(
                mapbox_style="open-street-map",
                mapbox_center={"lat": -33.45, "lon": -70.65}  # Centro de Santiago
            )

            st.plotly_chart(fig_mapa, use_container_width=True)

            # Leyenda
            col1, col2, col3 = st.columns(3)
            col1.markdown("🟢 **En movimiento** (>5 km/h)")
            col2.markdown("🟠 **En parada** (0-5 km/h)")
            col3.markdown("🔴 **Detenido** (0 km/h)")

    # Footer
    st.markdown("---")
    st.markdown(
        "💡 **Tip**: Los datos se actualizan automáticamente cada 10 minutos vía GitHub Actions. "
        "Usa el botón 'Actualizar datos' en la barra lateral para refrescar el dashboard."
    )

if __name__ == "__main__":
    main()
