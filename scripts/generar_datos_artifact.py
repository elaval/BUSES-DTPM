"""Genera data_vivo.json (flota de los últimos 7 días) para el dashboard
(GitHub Pages y artifact de Claude).

Uso:
    python scripts/generar_datos_artifact.py salida.json

Lee data/metricas_historicas.parquet y data/operadores.json locales si existen
(caso GitHub Actions, justo después de una captura); si no, los lee desde GitHub.
"""
import json, sys, urllib.request
from pathlib import Path
import pandas as pd

BASE = 'https://raw.githubusercontent.com/elaval/BUSES-DTPM/'
local_h, local_o, local_r = Path('data/metricas_historicas.parquet'), Path('data/operadores.json'), Path('data/datos_recientes.parquet')
h = pd.read_parquet(local_h if local_h.exists() else BASE + 'data/data/metricas_historicas.parquet')
ops = json.loads(local_o.read_text(encoding='utf-8') if local_o.exists()
                 else urllib.request.urlopen(BASE + 'main/data/operadores.json').read())

op = h[h.nivel == 'operador'].copy()
fin = op.timestamp.max()
ini = fin - pd.Timedelta(days=7)
w = op[op.timestamp > ini]
agg = w.groupby('timestamp').agg(total=('total_buses', 'sum'), mov=('buses_en_movimiento', 'sum'),
                                 sin=('buses_sin_senal', 'sum'), nsin=('buses_sin_senal', 'count')).reset_index()
serie = [[t.strftime('%Y-%m-%dT%H:%M'), int(a), int(b), (int(c) if n > 0 else None)]
         for t, a, b, c, n in zip(agg.timestamp, agg.total, agg.mov, agg.sin, agg.nsin)]

u = op[op.timestamp == fin]
ahora = [{'id': int(r.operador), 'nombre': ops.get(str(int(r.operador)), f'Operador {r.operador}'),
          'total': int(r.total_buses), 'mov': int(r.buses_en_movimiento),
          'sin': (None if pd.isna(r.buses_sin_senal) else int(r.buses_sin_senal))} for r in u.itertuples()]

# Perfil horario de días hábiles: histórico completo vs últimos 7 días (mediana por hora)
t = op.groupby('timestamp').buses_en_movimiento.sum()
t = t[t.index.dayofweek < 5]
hist = t.groupby(t.index.hour).median()
rec = t[t.index > ini]
rec = rec.groupby(rec.index.hour).median()
perfil = [{'h': k, 'historico': int(hist.get(k, 0)), 'semana': (int(rec[k]) if k in rec else None)}
          for k in range(24)]

# Flota de referencia: buses distintos (patentes) con señal en los últimos 7 días
r = pd.read_parquet(local_r if local_r.exists() else BASE + 'data/data/datos_recientes.parquet', columns=['timestamp', 'patente', 'operador'])
r7 = r[r.timestamp > r.timestamp.max() - pd.Timedelta(days=7)]
flota_7d = int(r7.patente.nunique())
flota_op = r7.groupby('operador').patente.nunique()   # un bus puede aparecer en 2 operadores si cambió de unidad

for o_ in ahora:
    o_['flota_7d'] = int(flota_op.get(o_['id'], 0))

out = {'actualizado': fin.strftime('%Y-%m-%dT%H:%M'), 'capturas_7d': int(len(agg)), 'flota_7d': flota_7d,
       'serie': serie, 'ahora': ahora, 'perfil': perfil}
salida = sys.argv[1] if len(sys.argv) > 1 else 'data_vivo.json'
Path(salida).write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('data_vivo.json:', out['actualizado'], len(serie), 'capturas')
