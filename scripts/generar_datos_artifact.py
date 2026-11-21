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

# Capturas demasiado juntas (p. ej. cron de respaldo de GitHub 1 min antes de la
# de cron-job.org): se descarta la primera del par. Si no, la ventana de
# "operando" se acorta y la serie muestra muescas.
MIN_SEPARACION_MIN = 6
tsh = pd.Series(sorted(op.timestamp.unique()))
descartar = set(tsh[(tsh.shift(-1) - tsh).dt.total_seconds() / 60 < MIN_SEPARACION_MIN])
op = op[~op.timestamp.isin(descartar)]
w = op[op.timestamp > ini]
agg = w.groupby('timestamp').agg(total=('total_buses', 'sum'), mov=('buses_en_movimiento', 'sum'),
                                 sin=('buses_sin_senal', 'sum'), nsin=('buses_sin_senal', 'count')).reset_index()
serie_base = list(zip(agg.timestamp, agg.total, agg.mov, agg.sin, agg.nsin))

u = op[op.timestamp == fin]
ahora = [{'id': int(r.operador), 'nombre': ops.get(str(int(r.operador)), f'Operador {r.operador}'),
          'total': int(r.total_buses), 'mov': int(r.buses_en_movimiento),
          'sin': (None if pd.isna(r.buses_sin_senal) else int(r.buses_sin_senal))} for r in u.itertuples()]

# Flota de referencia: buses distintos (patentes) con señal en los últimos 7 días
r = pd.read_parquet(local_r if local_r.exists() else BASE + 'data/data/datos_recientes.parquet')
r7 = r[r.timestamp > r.timestamp.max() - pd.Timedelta(days=7)]
r7 = r7.drop_duplicates(subset=['patente', 'timestamp'], keep='last')   # una fila por bus y captura
r7 = r7[~r7.timestamp.isin(descartar)]
flota_7d = int(r7.patente.nunique())
flota_op = r7.groupby('operador').patente.nunique()   # un bus puede aparecer en 2 operadores si cambió de unidad

# Buses operando (se movieron en los últimos ~20 min), solo donde hay capturas cada ~10 min
sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import marcar_operando, VENTANA_OPERANDO_MIN  # noqa: E402
m = marcar_operando(r7)
m['opc'] = m.operando & m.comercial
m['opt'] = m.operando & ~m.comercial
m['opc_mov'] = m.opc & (m.estado == 'en_movimiento')
tsu = pd.Series(sorted(m.timestamp.unique()))
# Captura "densa": la anterior está dentro de la ventana de "operando" (tolera
# que falte una captura de 10 min) y hay al menos dos previas recientes.
dmin = tsu.diff().dt.total_seconds() / 60
d2min = tsu.diff(2).dt.total_seconds() / 60
densa = set(tsu[(dmin <= VENTANA_OPERANDO_MIN) & (d2min <= 40)])
opx = m.groupby('timestamp')[['opc', 'opt', 'opc_mov']].sum()

# Día hábil típico: buses en servicio, mediana por hora de los días hábiles de los últimos 7 días
# (solo capturas cada ~10 min: la misma medida del gráfico de los últimos 7 días)
pv = opx.opc[[t in densa and t.dayofweek < 5 for t in opx.index]]
perfil = [{'h': int(k), 'servicio': int(v)} for k, v in pv.groupby(pv.index.hour).median().items()]
perfil_dias = int(pv.index.normalize().nunique())
ult = m[m.timestamp == m.timestamp.max()].groupby('operador')[['opc', 'opt']].sum()

for o_ in ahora:
    o_['flota_7d'] = int(flota_op.get(o_['id'], 0))
    if fin in densa and o_['id'] in ult.index:
        o_['op_com'], o_['op_ts'] = int(ult.loc[o_['id'], 'opc']), int(ult.loc[o_['id'], 'opt'])

# serie: [t, total, mov, sin, operando_comercial, operando_ts, operando_comercial_en_movimiento]
serie = []
for t, a, b, c, n in serie_base:
    fila = [t.strftime('%Y-%m-%dT%H:%M'), int(a), int(b), (int(c) if n > 0 else None)]
    if t in densa and t in opx.index:
        fila += [int(opx.loc[t, 'opc']), int(opx.loc[t, 'opt']), int(opx.loc[t, 'opc_mov'])]
    serie.append(fila)

out = {'actualizado': fin.strftime('%Y-%m-%dT%H:%M'), 'capturas_7d': int(len(agg)), 'flota_7d': flota_7d,
       'serie': serie, 'ahora': ahora, 'perfil': perfil, 'perfil_dias': perfil_dias}
salida = sys.argv[1] if len(sys.argv) > 1 else 'data_vivo.json'
Path(salida).write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('data_vivo.json:', out['actualizado'], len(serie), 'capturas')
