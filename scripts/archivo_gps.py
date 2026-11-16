"""
Archivo permanente de los datos GPS bus por bus.

data/datos_recientes.parquet guarda solo 7 días. Cada día completo se sube como
archivo_gps_AAAA-MM-DD.parquet al Release `archivo-gps-diario`. Lo hace el monitor
en cada captura (scripts/monitor.py) y, como respaldo, el workflow archivo-diario.yaml
(scripts/archivar_dias.py).

Para no consultar a GitHub en cada captura, data/archivados.json registra los días
ya subidos: solo cuando aparece un día completo que no está ahí se revisa el Release
y se sube lo que falte.
"""
import json
import subprocess
from pathlib import Path

import pandas as pd

RELEASE = 'archivo-gps-diario'
# Lo anterior está en el Release archivo-gps-2026-11 (8-may a 14-nov-2026)
INICIO = pd.Timestamp('2026-11-15')
NOTAS = ('Datos GPS bus por bus, un archivo por día (hora de Chile), con capturas cada '
         '~10 min desde el 15-nov-2026. Mismas columnas que data/datos_recientes.parquet '
         '(ver data/README.md). Lo anterior está en el Release archivo-gps-2026-11.')


def compactar(df):
    """Formato compacto para guardar datos bus por bus.

    float32 (≈0,4 m de precisión en las coordenadas) y filas ordenadas por bus:
    con compresión zstd, una semana de capturas cada 10 min pesa ~30 MB en vez de
    ~115 MB (GitHub rechaza archivos de más de 100 MB).
    """
    df = df.copy()
    for c in df.select_dtypes('float64').columns:
        df[c] = df[c].astype('float32')
    return df.sort_values(['patente', 'timestamp'], kind='stable')


def escribir_parquet(df, ruta):
    compactar(df).to_parquet(ruta, index=False, compression='zstd', compression_level=9)


def nombre_dia(dia):
    return f'archivo_gps_{dia:%Y-%m-%d}.parquet'


def dias_completos(ts):
    """Días (desde INICIO) que están enteros en la serie de timestamps."""
    primero, ultimo = ts.min(), ts.max()
    dias = pd.date_range(max(INICIO, primero.normalize()), ultimo.normalize() - pd.Timedelta(days=1))
    return [x for x in dias if primero <= x + pd.Timedelta(minutes=10)]


def _gh(*args):
    return subprocess.run(['gh', *args], capture_output=True, text=True)


def archivos_en_release():
    """Nombres de los archivos ya subidos (crea el Release si no existe)."""
    if _gh('release', 'view', RELEASE).returncode != 0:
        r = _gh('release', 'create', RELEASE, '--title', 'Archivo GPS diario (bus por bus)', '--notes', NOTAS)
        if r.returncode != 0 and _gh('release', 'view', RELEASE).returncode != 0:
            raise RuntimeError(f'No se pudo crear el Release {RELEASE}: {r.stderr.strip()}')
    r = _gh('release', 'view', RELEASE, '--json', 'assets')
    if r.returncode != 0:
        raise RuntimeError(f'No se pudo leer el Release {RELEASE}: {r.stderr.strip()}')
    return {a['name'] for a in json.loads(r.stdout)['assets']}


def archivar_pendientes(d, registro=None, salida='archivo', subir=True):
    """Sube los días completos de `d` que aún no están archivados. Devuelve cuántos subió.

    registro: ruta de archivados.json (o None para consultar siempre el Release).
    """
    registro = Path(registro) if registro else None
    hechos = set(json.loads(registro.read_text())) if registro and registro.exists() else set()
    pendientes = [x for x in dias_completos(d.timestamp) if nombre_dia(x) not in hechos]
    if not pendientes:
        return 0

    if subir:
        en_release = archivos_en_release()
        hechos |= en_release
        pendientes = [x for x in pendientes if nombre_dia(x) not in en_release]

    out = Path(salida)
    out.mkdir(exist_ok=True)
    subidos = 0
    for dia in pendientes:
        nombre = nombre_dia(dia)
        sub = d[(d.timestamp >= dia) & (d.timestamp < dia + pd.Timedelta(days=1))]
        if sub.empty:
            print(f'   ⚠️  {dia:%Y-%m-%d}: sin capturas, no se archiva')
            hechos.add(nombre)
            continue
        ruta = out / nombre
        escribir_parquet(sub, ruta)
        if subir:
            r = _gh('release', 'upload', RELEASE, str(ruta))
            # Si falló porque otra corrida lo subió recién, igual cuenta como archivado
            if r.returncode != 0 and nombre not in archivos_en_release():
                print(f'   ⚠️  {nombre}: no se pudo subir ({r.stderr.strip()}); se reintenta en la próxima captura')
                continue
        print(f'   📦 {nombre}: {sub.timestamp.nunique()} capturas, {len(sub):,} filas, '
              f'{ruta.stat().st_size / 1e6:.1f} MB{" → Release " + RELEASE if subir else " (local)"}')
        hechos.add(nombre)
        subidos += 1

    if registro:
        registro.write_text(json.dumps(sorted(hechos), indent=0))
    return subidos
