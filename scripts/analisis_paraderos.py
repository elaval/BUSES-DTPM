"""
Análisis de velocidad por TRAMO entre paraderos y por recorrido, para el dashboard.

Genera:
  pagina/data_estatico.json  -> tramos de la red (entre paraderos consecutivos) con
                                velocidad en punta y valle, comunas y tramos más lentos
  pagina/lineas.json         -> por recorrido: buses por hora, paraderos y velocidad
                                por tramo; más el índice paradero -> recorridos de la red

Entradas:
  --archivo  uno o más parquet con el detalle bus por bus: el del Release
             archivo-gps-2026-11, los diarios del Release archivo-gps-diario y
             datos_recientes.parquet (los registros repetidos se eliminan)
  --gtfs     zip GTFS oficial del DTPM (Release insumos-dtpm)
  --excel    Servicios_decos_*.xlsx (código interno -> recorrido público; Release insumos-dtpm)

  En GitHub lo corre .github/workflows/analisis-lineas.yaml, que publica
  lineas.json y data_estatico.json en el Release analisis-lineas.

Uso:
  pip install pandas pyarrow openpyxl shapely
  python scripts/analisis_paraderos.py --archivo data/archivo_gps_2026-05-08_a_2026-11-14.parquet \
      --gtfs docs/gtfs/GTFS_20260704.zip --excel docs/Servicios_decos_09022026.xlsx

Método:
  - Días hábiles; GPS con antigüedad real <= 10 min (corrige el desfase UTC de los
    datos anteriores al 15-nov-2026); solo buses EN MOVIMIENTO (> 5 km/h); sin
    servicios "TS" (sin servicio comercial).
  - Cada posición se proyecta sobre el trazado oficial (GTFS shapes) de SU recorrido
    y sentido (a menos de 60 m del trazado) y se asigna al tramo entre los dos
    paraderos consecutivos que la rodean. Se excluyen los primeros y últimos 400 m
    del recorrido (terminales).
  - Velocidad del tramo = mediana de velocidad_promedio (promedio de las 4 últimas
    transmisiones GPS) de los buses en movimiento en ese tramo. No incluye el
    tiempo detenido en paraderos: es la velocidad de circulación, no la comercial.
  - Punta = 7-9 h y 18-20 h; valle = 11-16 h.
  - En lineas.json, un tramo con menos de MIN_LINEA registros en un período toma la
    mediana de sus registros junto con los de 1 (o, si no alcanza, 2) tramos vecinos
    por lado, y queda marcado como aproximado. Es transitorio: en cuanto el tramo
    junta sus propios registros, usa su valor propio.
"""
import argparse, io, json, re, urllib.request, warnings, zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point, mapping, shape
from shapely.strtree import STRtree

warnings.filterwarnings('ignore')
URL_COMUNAS = 'https://raw.githubusercontent.com/caracena/chile-geojson/master/13.geojson'
PERIODO = {7: 'am', 8: 'am', 18: 'pm', 19: 'pm', 11: 'valle', 12: 'valle', 13: 'valle', 14: 'valle', 15: 'valle'}
LAT0 = -33.45
KX, KY = np.cos(np.radians(LAT0)) * 111320, 110540
MIN_RED = {'am': 30, 'pm': 30, 'valle': 60}   # mínimos de registros por tramo de la red
MIN_LINEA = 8                                  # mínimo por tramo y período en una línea
VECINOS_MAX = 2                                # tramos vecinos (por lado) para aproximar
APROX = {'am': 1, 'pm': 2, 'valle': 4}         # bits de "valor aproximado" en lineas.json


def a_xy(lon, lat):
    return np.c_[(np.asarray(lon) + 70.65) * KX, (np.asarray(lat) - LAT0) * KY]


def a_lonlat(xy):
    xy = np.asarray(xy)
    return np.c_[xy[:, 0] / KX - 70.65, xy[:, 1] / KY + LAT0]


def edad_real(a):
    """Antigüedad real del GPS: antes del 15-nov-2026 hay que sumar el desfase UTC."""
    ts = pd.Series(a.timestamp.unique())
    off = {t: -pd.Timestamp(t).tz_localize(ZoneInfo('America/Santiago'), ambiguous=True,
                                           nonexistent='shift_forward').utcoffset().total_seconds() / 60
           for t in ts}
    corr = a.timestamp.map(off).where(a.timestamp < '2026-11-15 00:00', 0)
    return a.edad_datos_min + corr


COLUMNAS = ['timestamp', 'patente', 'servicio', 'sentido', 'estado', 'edad_datos_min',
            'latitud', 'longitud', 'velocidad_promedio']


def leer_gps(rutas):
    """Une los archivos GPS (histórico + diarios), dejando solo días hábiles con GPS al día.

    Se filtra archivo por archivo para no cargar en memoria lo que no se usa.
    """
    partes = []
    for r in sorted(rutas):
        a = pd.read_parquet(r, columns=COLUMNAS)
        a['edad'] = edad_real(a)
        partes.append(a[(a.timestamp.dt.dayofweek < 5) & a.edad.between(0, 10)])
    a = pd.concat(partes, ignore_index=True).drop_duplicates(['patente', 'timestamp'])
    print(f'{len(rutas)} archivos GPS: {len(a):,} registros hábiles, '
          f'{a.timestamp.nunique():,} capturas ({a.timestamp.min():%d-%m-%Y} a {a.timestamp.max():%d-%m-%Y})')
    return a


def limpio(n):
    return re.sub(r'^[A-Z]+\d+-', '', n)


def calle_cruce(n):
    """('Av. Cristóbal Colón', 'Alcántara') a partir de 'PA12-Av. Cristóbal Colón / esq. Alcántara'."""
    a_, _, b = limpio(n).partition(' / ')
    b = b.replace('esq. ', '').strip()
    if a_.lower().startswith('parada'):
        return '', b                      # paradero de estación: sin calle, solo el hito
    c = re.sub(r'^(Avenida|Avda\.?|Av)\s+', 'Av. ', a_.strip()).replace('Av. Av.', 'Av.')
    return c, b


def nombre_tramo(n1, n2):
    c1, x1 = calle_cruce(n1)
    c2, x2 = calle_cruce(n2)
    calle = c1 or c2
    if calle:
        return calle, f'entre {x1 or limpio(n1)} y {x2 or limpio(n2)}'
    return x1, f'entre {x1} y {x2}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archivo', required=True, nargs='+', help='Uno o más parquet GPS')
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

    # --- GTFS: trazado y paraderos de un viaje representativo por recorrido y sentido
    z = zipfile.ZipFile(args.gtfs)
    rd = lambda n, **k: pd.read_csv(io.BytesIO(z.read(n)), dtype=str, **k)
    routes = rd('routes.txt').set_index('route_short_name').route_long_name.to_dict()
    t = rd('trips.txt')
    t = t[t.shape_id.str[-1].isin(['I', 'R'])].copy()
    t['dir'] = t.shape_id.str[-1]
    rep = t.drop_duplicates(['route_id', 'dir'])[['route_id', 'dir', 'trip_id', 'shape_id', 'trip_headsign']]
    sh = rd('shapes.txt')
    sh = sh[sh.shape_id.isin(rep.shape_id)]
    sh[['shape_pt_lat', 'shape_pt_lon']] = sh[['shape_pt_lat', 'shape_pt_lon']].astype(float)
    sh['shape_pt_sequence'] = sh.shape_pt_sequence.astype(int)
    lineas_geo = {k: LineString(a_xy(g.shape_pt_lon, g.shape_pt_lat))
                  for k, g in sh.sort_values('shape_pt_sequence').groupby('shape_id') if len(g) > 1}
    st = rd('stop_times.txt', usecols=['trip_id', 'stop_id', 'stop_sequence'])
    st['stop_sequence'] = st.stop_sequence.astype(int)
    st = st[st.trip_id.isin(rep.trip_id)].merge(rep, on='trip_id').sort_values(['route_id', 'dir', 'stop_sequence'])
    stops = rd('stops.txt')[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']]
    stops[['stop_lat', 'stop_lon']] = stops[['stop_lat', 'stop_lon']].astype(float)
    st = st.merge(stops, on='stop_id')

    # Recorridos: paraderos con su posición (km) sobre el trazado
    REC = {}
    for (r, dr), s in st.groupby(['route_id', 'dir']):
        line = lineas_geo.get(s.shape_id.iloc[0])
        if line is None or len(s) < 3:
            continue
        s = s.reset_index(drop=True)
        ch = shapely.line_locate_point(line, shapely.points(a_xy(s.stop_lon, s.stop_lat)))
        ch = np.maximum.accumulate(ch)                    # monotonía ante pequeños retrocesos
        REC[(r, dr)] = {'line': line, 'stops': s, 'ch': ch, 'destino': s.trip_headsign.iloc[0]}

    # --- datos GPS
    hab = leer_gps(args.archivo)
    hab['h'] = hab.timestamp.dt.hour
    periodo_txt = args.periodo or f"días hábiles, {hab.timestamp.min():%d-%m-%Y} a {hab.timestamp.max():%d-%m-%Y}"
    d = hab[(hab.estado == 'en_movimiento') & (~hab.servicio.fillna('').str.endswith('TS')) &
            (hab.servicio.fillna('') != '')]
    d = d.assign(periodo=d.h.map(PERIODO), pub=d.servicio.map(srv2pub)).dropna(subset=['periodo', 'pub', 'sentido'])
    print('registros en movimiento (punta/valle):', len(d))

    # --- asignar cada posición al tramo entre paraderos de su recorrido y sentido
    asig = []
    for (r, dr), g in d.groupby(['pub', 'sentido']):
        R = REC.get((r, dr))
        if R is None:
            continue
        pts = shapely.points(a_xy(g.longitud, g.latitud))
        dist = shapely.distance(R['line'], pts)
        pos = shapely.line_locate_point(R['line'], pts)
        ch = R['ch']
        k = np.searchsorted(ch, pos, side='right') - 1
        ok = (dist < 60) & (pos > 400) & (pos < R['line'].length - 400) & (k >= 0) & (k < len(ch) - 1)
        gg = g[ok][['periodo', 'velocidad_promedio']].copy()
        gg['ruta'], gg['dir'], gg['k'] = r, dr, k[ok]
        asig.append(gg)
    o = pd.concat(asig)
    print('registros asignados a tramos:', len(o))

    # --- por tramo de cada recorrido
    v = o.groupby(['ruta', 'dir', 'k', 'periodo']).velocidad_promedio.agg(['median', 'size']).unstack()
    v.columns = [f'{m}_{p}' for m, p in v.columns]
    # registros de cada tramo, para aproximar con los vecinos los que tienen pocos
    regs = {key: g.to_numpy() for key, g in o.groupby(['ruta', 'dir', 'periodo', 'k']).velocidad_promedio}

    # --- tramos de la red: mismo par de paraderos, todas las líneas juntas
    def par_id(r, dr, k):
        s = REC[(r, dr)]['stops']
        return s.stop_id.iloc[k] + '>' + s.stop_id.iloc[k + 1]
    o['par'] = [par_id(r, dr, k) for r, dr, k in zip(o.ruta, o.dir, o.k)]
    gp = o.groupby(['par', 'periodo']).velocidad_promedio.agg(['median', 'size']).unstack()
    gp.columns = [f'{m}_{p}' for m, p in gp.columns]
    gp = gp[(gp.size_am >= MIN_RED['am']) & (gp.size_pm >= MIN_RED['pm']) & (gp.size_valle >= MIN_RED['valle'])].copy()
    gp['punta'] = gp[['median_am', 'median_pm']].min(axis=1)
    gp['caida'] = (1 - gp.punta / gp.median_valle) * 100
    gp['n_serv'] = o.groupby('par').ruta.nunique()
    # geometría y nombres de cada par: del primer recorrido que lo usa
    rep_par = o.drop_duplicates('par').set_index('par')[['ruta', 'dir', 'k']]

    from shapely.ops import substring

    def coords_tramo(r, dr, k, tol=12):
        R = REC[(r, dr)]
        seg = substring(R['line'], R['ch'][k], R['ch'][k + 1]).simplify(tol)
        c = np.asarray(seg.coords) if seg.length > 0 else np.asarray([seg.coords[0], seg.coords[0]])
        return [[round(lo, 5), round(la, 5)] for lo, la in a_lonlat(c)]

    # comunas
    gj = json.loads(urllib.request.urlopen(URL_COMUNAS).read())
    polys = [shape(f['geometry']) for f in gj['features']]
    names = [f['properties']['Comuna'] for f in gj['features']]
    tree = STRtree(polys)

    def comuna(lo, la):
        p = Point(lo, la)
        for i in tree.query(p):
            if polys[i].contains(p):
                return names[i]
        return '?'

    tramos_red = []
    filas = []
    for par, r_ in gp.iterrows():
        rr = rep_par.loc[par]
        s = REC[(rr.ruta, rr.dir)]['stops']
        n1, n2 = s.stop_name.iloc[rr.k], s.stop_name.iloc[rr.k + 1]
        calle, entre = nombre_tramo(n1, n2)
        cs = coords_tramo(rr.ruta, rr.dir, rr.k)
        mid = cs[len(cs) // 2]
        cm = comuna(*mid)
        tramos_red.append([cs, round(r_.punta, 1), round(r_.median_valle, 1), round(r_.caida), calle, entre, cm, int(r_.n_serv)])
        filas.append({'calle': calle, 'entre': entre, 'comuna': cm, 'punta': r_.punta, 'valle': r_.median_valle,
                      'caida': r_.caida, 'am': r_.median_am, 'pm': r_.median_pm, 'n_serv': r_.n_serv})
    f = pd.DataFrame(filas)
    # tabla: tramos más lentos (con 2+ servicios), uno por calle y comuna
    top = f[(f.n_serv >= 2) & (f.calle != '')].sort_values('punta').drop_duplicates(['calle', 'comuna']).head(15)
    tabla = [{'calle': (('Entorno Metro ' + r.calle.replace('(M) ', '')) if r.calle.startswith('(M)') else r.calle),
              'cruces': r.entre, 'comuna': r.comuna, 'punta': round(r.punta, 1), 'valle': round(r.valle, 1),
              'caida': round(r.caida), 'peor': 'mañana' if r.am < r.pm else 'tarde'} for r in top.itertuples()]

    feats = []
    for ft in gj['features']:
        s_ = shape(ft['geometry'])
        c = s_.centroid
        if -33.66 < c.y < -33.28 and -70.86 < c.x < -70.48:
            m = mapping(s_.simplify(0.0015))

            def rnd(v_):
                return [rnd(i) for i in v_] if isinstance(v_, (list, tuple)) and v_ and isinstance(v_[0], (list, tuple)) \
                    else [round(v_[0], 4), round(v_[1], 4)]
            feats.append({'type': 'Feature', 'properties': {'n': ft['properties']['Comuna']},
                          'geometry': {'type': m['type'], 'coordinates': rnd(m['coordinates'])}})

    out.mkdir(exist_ok=True)
    (out / 'data_estatico.json').write_text(json.dumps(
        {'tramos_red': tramos_red, 'comunas': {'type': 'FeatureCollection', 'features': feats}, 'tramos': tabla,
         'periodo': periodo_txt}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('data_estatico.json:', len(tramos_red), 'tramos de la red')

    # --- por recorrido
    act = hab[hab.estado != 'detenido'].assign(pub=lambda df: df.servicio.map(srv2pub)).dropna(subset=['pub'])
    cnt = act.groupby(['pub', 'timestamp']).size()
    allts = pd.Index(hab.timestamp.unique())
    bh = {}
    for p, s_ in cnt.groupby(level=0):
        s_ = s_.droplevel(0).reindex(allts, fill_value=0)
        bh[p] = [int(round(i)) for i in s_.groupby(s_.index.hour).median().reindex(range(24), fill_value=0)]

    L = {}
    for (r, dr), R in REC.items():
        if r not in bh:
            continue
        s, ch = R['stops'], R['ch']
        par = [[round(ch[i] / 1000, 2), limpio(s.stop_name.iloc[i]), round(s.stop_lat.iloc[i], 5), round(s.stop_lon.iloc[i], 5)]
               for i in range(len(s))]
        tr = []
        n_tramos = len(s) - 1
        for k in range(n_tramos):
            def mediana(x):
                m = np.nanmedian(x) if np.isfinite(x).any() else np.nan   # hay registros sin velocidad
                return None if np.isnan(m) else round(float(m), 1)

            def val(per):
                """(velocidad, aproximada): propia si hay MIN_LINEA registros; si no, con vecinos."""
                propios = regs.get((r, dr, per, k))
                if propios is not None and len(propios) >= MIN_LINEA:
                    return mediana(propios), False
                for w_ in range(1, VECINOS_MAX + 1):
                    x = [regs.get((r, dr, per, j)) for j in range(max(0, k - w_), min(n_tramos, k + w_ + 1))]
                    x = [a_ for a_ in x if a_ is not None]
                    if x and sum(map(len, x)) >= MIN_LINEA:
                        m = mediana(np.concatenate(x))
                        return (m, m is not None)
                return None, False
            (am, xa), (pm, xp), (va, xv) = val('am'), val('pm'), val('valle')
            aprox = APROX['am'] * xa + APROX['pm'] * xp + APROX['valle'] * xv
            tr.append([k, am, pm, va, coords_tramo(r, dr, k, tol=15), aprox])
        L.setdefault(r, {'nombre': routes.get(r, ''), 'operador': pub2op.get(r, ''), 'buses_hora': bh[r], 'sentidos': {}})
        L[r]['sentidos'][dr] = {'destino': R['destino'], 'paraderos': par, 'tramos': tr}

    sr = st[st.route_id.isin(L.keys())].groupby('stop_id').route_id.apply(
        lambda x: sorted(set(x), key=lambda r: (len(r), r))).reset_index().merge(stops, on='stop_id')
    red = [[round(r.stop_lat, 5), round(r.stop_lon, 5), limpio(r.stop_name), r.route_id] for r in sr.itertuples()]
    (out / 'lineas.json').write_text(json.dumps({'lineas': L, 'red': red}, ensure_ascii=False, separators=(',', ':')),
                                     encoding='utf-8')
    print('lineas.json:', len(L), 'recorridos,', len(red), 'paraderos de la red')


if __name__ == '__main__':
    main()
