"""
Archiva los datos bus por bus antes de que salgan de la ventana de 7 días.

Cada día completo que esté en data/datos_recientes.parquet y aún no esté archivado
se guarda como archivo_gps_AAAA-MM-DD.parquet en el Release `archivo-gps-diario`.
Si una corrida falla, la siguiente recupera los días pendientes (mientras sigan
dentro de los 7 días).

Uso:
  python scripts/archivar_dias.py data/datos_recientes.parquet           # sube al Release
  python scripts/archivar_dias.py data/datos_recientes.parquet --local   # solo escribe en archivo/
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from monitor import escribir_parquet  # noqa: E402

RELEASE = 'archivo-gps-diario'
# Lo anterior está en el Release archivo-gps-2026-11 (8-may a 14-nov-2026)
INICIO = pd.Timestamp('2026-11-15')
NOTAS = ('Datos GPS bus por bus, un archivo por día (hora de Chile), con capturas cada '
         '~10 min desde el 15-nov-2026. Mismas columnas que data/datos_recientes.parquet '
         '(ver data/README.md). Lo anterior está en el Release archivo-gps-2026-11.')


def gh(*args, check=True):
    return subprocess.run(['gh', *args], capture_output=True, text=True, check=check)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('origen', nargs='?', default='data/datos_recientes.parquet')
    ap.add_argument('--salida', default='archivo')
    ap.add_argument('--local', action='store_true', help='No subir al Release')
    args = ap.parse_args()

    existentes = set()
    if not args.local:
        if gh('release', 'view', RELEASE, check=False).returncode != 0:
            gh('release', 'create', RELEASE, '--title', 'Archivo GPS diario (bus por bus)', '--notes', NOTAS)
            print(f'Release {RELEASE} creado')
        existentes = {a['name'] for a in json.loads(gh('release', 'view', RELEASE, '--json', 'assets').stdout)['assets']}

    d = pd.read_parquet(args.origen)
    primero, ultimo = d.timestamp.min(), d.timestamp.max()
    # Días completos: el primero empieza dentro de la ventana y el último ya terminó
    dias = pd.date_range(max(INICIO, primero.normalize()), ultimo.normalize() - pd.Timedelta(days=1))
    dias = [x for x in dias if primero <= x + pd.Timedelta(minutes=10)]

    out = Path(args.salida)
    out.mkdir(exist_ok=True)
    subidos = 0
    for dia in dias:
        nombre = f'archivo_gps_{dia:%Y-%m-%d}.parquet'
        if nombre in existentes:
            continue
        sub = d[(d.timestamp >= dia) & (d.timestamp < dia + pd.Timedelta(days=1))]
        if sub.empty:
            print(f'⚠️  {dia:%Y-%m-%d}: sin capturas')
            continue
        ruta = out / nombre
        escribir_parquet(sub, ruta)
        print(f'{nombre}: {sub.timestamp.nunique()} capturas, {len(sub):,} filas, '
              f'{ruta.stat().st_size / 1e6:.1f} MB')
        if not args.local:
            gh('release', 'upload', RELEASE, str(ruta))
            subidos += 1
    print(f'Listo: {subidos} archivos subidos, {len(existentes)} ya estaban')


if __name__ == '__main__':
    main()
