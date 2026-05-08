"""
Script para generar mapeo de operadores desde datos capturados
Analiza los datos reales y crea un diccionario de ID → Nombre
"""

import pandas as pd
import json
from pathlib import Path
from collections import Counter

# Leer datos recientes
df = pd.read_parquet('data/datos_recientes.parquet')

# Obtener operadores y servicios únicos
df_operadores = df[['operador', 'servicio']].drop_duplicates()

print(f"=== ANÁLISIS DE OPERADORES ===")
print(f"Total operadores únicos: {df['operador'].nunique()}")
print(f"Total servicios únicos: {df['servicio'].nunique()}")

# Leer Excel oficial si existe
excel_path = Path('docs/Servicios_decos_09022026.xlsx')
if excel_path.exists():
    print(f"\n✅ Encontrado archivo oficial: {excel_path}")
    df_excel = pd.read_excel(excel_path)

    # Crear mapeo servicio → operador_nombre
    servicio_a_operador = dict(zip(
        df_excel['SERVICIO_DECO'].astype(str).str.strip(),
        df_excel['CLI_DSC']
    ))

    # Inferir ID numérico → nombre de operador
    # Agrupando servicios por operador numérico y viendo qué nombres aparecen
    operador_nombres = {}

    for op_id in sorted(df['operador'].unique()):
        # Obtener servicios de este operador
        servicios_op = df[df['operador'] == op_id]['servicio'].unique()

        # Buscar nombres de operador en Excel
        nombres_encontrados = []
        for servicio in servicios_op:
            servicio_clean = str(servicio).strip()
            if servicio_clean in servicio_a_operador:
                nombres_encontrados.append(servicio_a_operador[servicio_clean])

        # Usar el nombre más común
        if nombres_encontrados:
            nombre_mas_comun = Counter(nombres_encontrados).most_common(1)[0][0]
            operador_nombres[int(op_id)] = nombre_mas_comun
        else:
            operador_nombres[int(op_id)] = f"Operador {op_id}"

    print(f"\n=== MAPEO GENERADO ===")
    for op_id, nombre in sorted(operador_nombres.items()):
        n_buses = len(df[df['operador'] == op_id])
        print(f"{op_id:3d}: {nombre:40s} ({n_buses:,} registros)")

    # Guardar en JSON
    output_path = Path('data/operadores.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(operador_nombres, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Mapeo guardado en: {output_path}")

else:
    print(f"\n⚠️  No se encontró archivo oficial en {excel_path}")
    print("Generando mapeo básico desde datos...")

    # Mapeo básico
    operador_nombres = {int(op_id): f"Operador {op_id}"
                       for op_id in df['operador'].unique()}

    # Guardar
    output_path = Path('data/operadores.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(operador_nombres, f, ensure_ascii=False, indent=2)

    print(f"✅ Mapeo básico guardado en: {output_path}")
