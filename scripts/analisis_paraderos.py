"""
Análisis de velocidad por paradero y por recorrido, para el dashboard.

Genera:
  pagina/data_estatico.json  -> velocidad por paradero, comunas y tramos más lentos
  pagina/lineas.json         -> por recorrido: buses por hora y velocidad por paradero,
                                más el índice paradero -> recorridos de toda la red

Entradas:
  --archivo  parquet con el detalle bus por bus (p. ej. el del Release
             archivo-gps-2026-11, o datos_recientes.parquet de la rama data)
  --gtfs     zip GTFS oficial del DTPM (https://www.dtpm.cl/descargas/gtfs/...)
  --excel    docs/Servicios_decos_*.xlsx (código interno -> recorrido público)

Uso:
  pip install pandas pyarrow openpyxl scipy shapely
  python scripts/analisis_paraderos.py --archivo data/archivo_gps_2026-05-08_a_2026-11-14.parquet \
      --gtfs docs/gtfs/GTFS_20260704.zip --excel docs/Servicios_decos_09022026.xlsx

Método (resumen):
  - Días hábiles; GPS con antigüedad real <= 10 min (corrige el desfase UTC de los
    datos anteriores al 15-nov-2026); buses en movimiento; sin servicios "TS".
  - Cada posición se asigna al paradero más cercano (< 250 m) de SU recorrido y
    sentido; se excluyen los primeros/últimos 400 m (terminales).
  - Punta = 7-9 h y 18-20 h; valle = 11-16 h. Velocidad = mediana de
    velocidad_promedio (promedio de las 4 últimas transmisiones GPS).
"""
import argparse, io, json, re, urllib.request, warnings, zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

warnings.filterwarnings('ignore')
URL_COMUNAS = 'https://raw.githubusercontent.com/caracena/chile-geojson/master/13.geojson'
PERIODO = {7: 'am', 8: 'am', 18: 'pm', 19: 'pm', 11: 'valle', 12: 'valle', 13: 'valle', 14: 'valle', 15: 'valle'}
LAT0 = -33.45
KX, KY = np.cos(np.radians(LAT0)) * 111320, 110540


def xy(lat, lon):
    return np.c_[(lon + 70.65) * KX, (lat - LAT0) * KY]


def hav(a1, o1, a2, o2):
    p = np.pi / 180
    return 2 * 6371 * np.arcsin(np.sqrt(np.sin((a2 - a1) * p / 2) ** 2 +
                                        np.cos(a1 * p) * np.cos(a2 * p) * np.sin((o2 - o1) * p / 2) ** 2))


def edad_real(a):
    """Antigüedad real del GPS: antes del 15-nov-2026 hay que sumar el desfase UTC."""
    ts = pd.Series(a.timestamp.unique())
    off = {t: -pd.Timestamp(t).tz_localize(ZoneInfo('America/Santiago'), ambiguous=True,
                                           nonexistent='shift_forward').utcoffset().total_seconds() / 60
           for t in ts}
    corr = a.timestamp.map(off).where(a.timestamp < '2026-11-15 00:00', 0)
    return a.edad_datos_min + corr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archivo', required=True)
    ap.add_argument('--gtfs', required=True)
    ap.add_argument('--excel', required=True)
    ap.add_argument('--salida', default='pagina')
    ap.add_argument('--periodo', default=None, help='Texto del período para el dashboard')
    args = ap.parse_args()
    out = Path(args.salida)

    # --- código interno -> recorrido público, operador
    x = pd.read_excel(args.excel)
    x['srv'] = x.CODIGO_RUTA.astype(str).str.rsplit(' ', n=1).str[0].str.strip()
    x['pub'] = x.CODIGO_USUARIO.astype(str)
    srv2pub = x.drop_duplicates('srv').set_index('srv').pub.to_dict()
    pub2op = x.drop_duplicates('pub').set_index('pub').CLI_DSC.str.replace(r'^U\d+ - ', '', regex=True).to_dict()

    # --- GTFS
    z = zipfile.ZipFile(args.gtfs)
    rd = lambda n, **k: pd.read_csv(io.BytesIO(z.read(n)), dtype=str, **k)
    routes = rd('routes.txt').set_index('route_short_name').route_long_name.to_dict()
    t = rd('trips.txt')
    t = t[t.shape_id.str[-1].isin(['I', 'R'])].copy()
    t['dir'] = t.shape_id.str[-1]
    heads = t.drop_duplicates(['route_id', 'dir']).set_index(['route_id', 'dir']).trip_headsign.to_dict()
    rep = t.drop_duplicates(['route_id', 'dir'])[['route_id', 'dir', 'trip_id']]
    st = rd('stop_times.txt', usecols=['trip_id', 'stop_id', 'stop_sequence'])
    st['stop_sequence'] = st.stop_sequence.astype(int)
    st = st[st.trip_id.isin(rep.trip_id)].merge(rep, on='trip_id').sort_values(['route_id', 'dir', 'stop_sequence'])
    stops = rd('stops.txt')[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']]
    stops[['stop_lat', 'stop_lon']] = stops[['stop_lat', 'stop_lon']].astype(float)
    st = st.merge(stops, on='stop_id')

    # --- datos GPS
    a = pd.read_parquet(args.archivo)
    a['edad'] = edad_real(a)
    a['h'] = a.timestamp.dt.hour
    hab = a[(a.timestamp.dt.dayofweek < 5) & a.edad.between(0, 10)]
    periodo_txt = args.periodo or f"días hábiles, {a.timestamp.min():%d-%m-%Y} a {a.timestamp.max():%d-%m-%Y}"

    d = hab[(hab.estado == 'en_movimiento') & (~hab.servicio.fillna('').str.endswith('TS')) &
            (hab.servicio.fillna('') != '') & hab.latitud.between(-33.75, -33.25) & hab.longitud.between(-70.95, -70.45)]
    d = d.assign(periodo=d.h.map(PERIODO), pub=d.servicio.map(srv2pub)).dropna(subset=['periodo', 'pub', 'sentido'])
    print('registros en movimiento (punta/valle):', len(d))

    # --- asignar cada posición al paradero más cercano de su recorrido y sentido
    asig = []
    for (r, dr), g in d.groupby(['pub', 'sentido']):
        s = st[(st.route_id == r) & (st.dir == dr)]
        if len(s) < 3:
            continue
        P = xy(s.stop_lat.values, s.stop_lon.values)
        Q = xy(g.latitud.values, g.longitud.values)
        dist, idx = cKDTree(P).query(Q)
        dt = np.minimum(np.hypot(*(Q - P[0]).T), np.hypot(*(Q - P[-1]).T))
        ok = (dist < 250) & (dt > 400)
        gg = g[ok][['periodo', 'velocidad_promedio', 'pub', 'sentido']].copy()
        gg['stop_id'] = s.stop_id.values[idx[ok]]
        asig.append(gg)
    o = pd.concat(asig)
    print('registros asignados a paraderos:', len(o))

    # --- comunas
    gj = json.loads(urllib.request.urlopen(URL_COMUNAS).read())
    polys = [shape(f['geometry']) for f in gj['features']]
    names = [f['properties']['Comuna'] for f in gj['features']]
    tree = STRtree(polys)

    def comuna(la, lo):
        p = Point(lo, la)
        for i in tree.query(p):
            if polys[i].contains(p):
                return names[i]
        return '?'

    # --- velocidad por paradero (todas las líneas)
    g = o.groupby(['stop_id', 'periodo']).velocidad_promedio.agg(['median', 'size']).unstack()
    g.columns = [f'{x}_{y}' for x, y in g.columns]
    g = g.reset_index()
    g = g[(g.size_am >= 30) & (g.size_pm >= 30) & (g.size_valle >= 60)]
    g['punta'] = g[['median_am', 'median_pm']].min(axis=1)
    g['caida'] = (1 - g.punta / g.median_valle) * 100
    g = g.merge(o.groupby('stop_id').pub.nunique().rename('n_serv'), on='stop_id').merge(stops, on='stop_id')

    def limpio(n):
        return re.sub(r'^[A-Z]+\d+-', '', n)

    def calle(n):
        a_, _, b = limpio(n).partition(' / ')
        c = (b if a_.lower().startswith('parada') else a_).strip()
        return re.sub(r'^(Avenida|Avda\.?|Av)\s+', 'Av. ', c).replace('Av. Av.', 'Av.')

    def cruce(n):
        return limpio(n).partition(' / ')[2].replace('esq. ', '').strip()

    g['calle'] = g.stop_name.map(calle)
    g['cruce'] = g.stop_name.map(cruce)
    g['comuna'] = [comuna(la, lo) for la, lo in zip(g.stop_lat, g.stop_lon)]
    par = [[round(la, 5), round(lo, 5), round(p, 1), round(v, 1), round(c), limpio(n), cm]
           for la, lo, p, v, c, n, cm in zip(g.stop_lat, g.stop_lon, g.punta, g.median_valle, g.caida, g.stop_name, g.comuna)]

    feats = []
    for f in gj['features']:
        s_ = shape(f['geometry'])
        c = s_.centroid
        if -33.66 < c.y < -33.28 and -70.86 < c.x < -70.48:
            m = mapping(s_.simplify(0.0015))

            def rnd(v):
                return [rnd(i) for i in v] if isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)) \
                    else [round(v[0], 4), round(v[1], 4)]
            feats.append({'type': 'Feature', 'properties': {'n': f['properties']['Comuna']},
                          'geometry': {'type': m['type'], 'coordinates': rnd(m['coordinates'])}})

    q = g[g.n_serv >= 2]
    c = q.groupby(['calle', 'comuna']).agg(par=('stop_id', 'size'), punta=('punta', 'median'), valle=('median_valle', 'median'),
                                          caida=('caida', 'median'), am=('median_am', 'median'), pm=('median_pm', 'median')).reset_index()
    c = c[c.par >= 4].sort_values('punta').head(15)

    def cruces(cl, cm):
        return ', '.join(dict.fromkeys(q[(q.calle == cl) & (q.comuna == cm)].sort_values('punta').cruce.head(3)))
    tramos = [{'calle': r.calle.replace('(M) ', 'Entorno Metro '), 'comuna': r.comuna,
               'cruces': '' if r.calle.startswith('(M)') else cruces(r.calle, r.comuna),
               'punta': round(r.punta, 1), 'valle': round(r.valle, 1), 'caida': round(r.caida),
               'peor': 'mañana' if r.am < r.pm else 'tarde'} for r in c.itertuples()]
    out.mkdir(exist_ok=True)
    (out / 'data_estatico.json').write_text(json.dumps(
        {'paraderos': par, 'comunas': {'type': 'FeatureCollection', 'features': feats}, 'tramos': tramos, 'periodo': periodo_txt},
        ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('data_estatico.json:', len(par), 'paraderos')

    # --- por recorrido
    v = o.groupby(['pub', 'sentido', 'stop_id', 'periodo']).velocidad_promedio.agg(['median', 'size']).reset_index()
    act = hab[hab.estado != 'detenido'].assign(pub=lambda df: df.servicio.map(srv2pub)).dropna(subset=['pub'])
    cnt = act.groupby(['pub', 'timestamp']).size()
    allts = pd.Index(hab.timestamp.unique())
    bh = {}
    for p, s_ in cnt.groupby(level=0):
        s_ = s_.droplevel(0).reindex(allts, fill_value=0)
        bh[p] = [int(round(i)) for i in s_.groupby(s_.index.hour).median().reindex(range(24), fill_value=0)]

    L = {}
    for (r, dr), s_ in st.groupby(['route_id', 'dir']):
        if r not in bh:
            continue
        s_ = s_.reset_index(drop=True)
        km = np.r_[0, np.cumsum(hav(s_.stop_lat.values[:-1], s_.stop_lon.values[:-1], s_.stop_lat.values[1:], s_.stop_lon.values[1:]))]
        vv = v[(v.pub == r) & (v.sentido == dr)].pivot_table(index='stop_id', columns='periodo', values=['median', 'size'])
        rows = []
        for i, rw in s_.iterrows():
            def val(per):
                try:
                    return round(float(vv.loc[rw.stop_id, ('median', per)]), 1) if vv.loc[rw.stop_id, ('size', per)] >= 8 else None
                except KeyError:
                    return None
            rows.append([round(float(km[i]), 2), limpio(rw.stop_name), val('am'), val('pm'), val('valle'),
                         round(rw.stop_lat, 5), round(rw.stop_lon, 5)])
        L.setdefault(r, {'nombre': routes.get(r, ''), 'operador': pub2op.get(r, ''), 'buses_hora': bh[r], 'sentidos': {}})
        L[r]['sentidos'][dr] = {'destino': heads.get((r, dr), ''), 'paraderos': rows}

    sr = st[st.route_id.isin(L.keys())].groupby('stop_id').route_id.apply(
        lambda x: sorted(set(x), key=lambda r: (len(r), r))).reset_index().merge(stops, on='stop_id')
    red = [[round(r.stop_lat, 5), round(r.stop_lon, 5), limpio(r.stop_name), r.route_id] for r in sr.itertuples()]
    (out / 'lineas.json').write_text(json.dumps({'lineas': L, 'red': red}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('lineas.json:', len(L), 'recorridos,', len(red), 'paraderos de la red')


if __name__ == '__main__':
    main()
