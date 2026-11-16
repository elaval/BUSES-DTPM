"""
Respaldo del archivo diario (lo normal es que lo haga el monitor en cada captura).

Sube al Release `archivo-gps-diario` los días completos de datos_recientes.parquet
que aún no estén ahí. Ver scripts/archivo_gps.py.

Uso:
  python scripts/archivar_dias.py data/datos_recientes.parquet           # sube al Release
  python scripts/archivar_dias.py data/datos_recientes.parquet --local   # solo escribe en archivo/
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from archivo_gps import archivar_pendientes  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('origen', nargs='?', default='data/datos_recientes.parquet')
    ap.add_argument('--salida', default='archivo')
    ap.add_argument('--local', action='store_true', help='No subir al Release')
    args = ap.parse_args()
    n = archivar_pendientes(pd.read_parquet(args.origen), salida=args.salida, subir=not args.local)
    print(f'Listo: {n} días archivados')


if __name__ == '__main__':
    main()
