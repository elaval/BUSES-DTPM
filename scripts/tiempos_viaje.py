"""
Tiempo de viaje por recorrido, sentido y hora de salida.

Real: se sigue a cada bus entre capturas (cada ~10 min, desde el 15-nov-2026). Su
posición se proyecta sobre el trazado y, por interpolación, se estima a qué hora
pasó por el km A y por el km B. Se omiten los primeros y últimos ~3 km (10 % en
recorridos cortos), donde los buses entran y salen de terminales y depósitos.
Incluye todo lo que vive el pasajero: detenciones en paraderos, semáforos y
congestión (a diferencia de la velocidad por tramo, que solo mira buses en movimiento).

Programado: el mismo tramo, con los tiempos del GTFS (días hábiles), según la hora
de salida de cada franja de frecuencias.
"""
import numpy as np
import pandas as pd
import shapely

DENSO_DESDE = pd.Timestamp('2026-11-15')   # antes las capturas eran muy espaciadas
VENTANA_DIAS = 28                          # solo las últimas 4 semanas: condiciones recientes
MARGEN_MAX, MARGEN_FRAC = 3000, 0.10       # m / fracción del largo, en cada extremo
GAP_MAX = np.timedelta64(25, 'm')          # capturas más separadas cortan el viaje
RETROCESO = 800                            # m: si el bus vuelve atrás, empezó otro viaje
DIST_MAX = 120                             # m al trazado
MIN_VIAJES = 5                             # por hora, para publicar
HORAS = range(5, 24)


def limites(largo):
    m = min(MARGEN_MAX, MARGEN_FRAC * largo)
    return m, largo - m


def reales(hab, srv2pub, REC, a_xy):
    """{(recorrido, sentido): DataFrame(h, minutos)} siguiendo a cada bus."""
    d = hab[hab.timestamp >= max(DENSO_DESDE, hab.timestamp.max() - pd.Timedelta(days=VENTANA_DIAS))]
    d = d.assign(pub=d.servicio.map(srv2pub)).dropna(subset=['pub', 'sentido'])
    out = {}
    for (r, dr), g in d.groupby(['pub', 'sentido']):
        R = REC.get((r, dr))
        if R is None:
            continue
        L = R['line']
        A, B = limites(L.length)
        P = shapely.points(a_xy(g.longitud, g.latitud))
        g = g.assign(dist=shapely.distance(L, P), km=shapely.line_locate_point(L, P))
        g = g[g.dist < DIST_MAX].sort_values(['patente', 'timestamp'])
        if len(g) < 10:
            continue
        pat = g.patente.to_numpy()
        t = g.timestamp.to_numpy()
        km = g.km.to_numpy()
        corte = np.flatnonzero((pat[1:] != pat[:-1]) | (np.diff(t) > GAP_MAX) | (np.diff(km) < -RETROCESO)) + 1
        ts = t.astype('datetime64[s]').astype(np.int64)
        filas = []
        for i0, i1 in zip(np.r_[0, corte], np.r_[corte, len(g)]):
            if i1 - i0 < 3:
                continue
            kk = np.maximum.accumulate(km[i0:i1])
            if kk[0] > A or kk[-1] < B:
                continue
            tt = ts[i0:i1]
            iA = np.searchsorted(kk, A, side='right')
            iB = np.searchsorted(kk, B, side='left')
            if iA == 0 or iA >= len(kk) or iB == 0 or iB >= len(kk):
                continue
            tA = tt[iA - 1] + (A - kk[iA - 1]) / max(kk[iA] - kk[iA - 1], 1) * (tt[iA] - tt[iA - 1])
            tB = tt[iB - 1] + (B - kk[iB - 1]) / max(kk[iB] - kk[iB - 1], 1) * (tt[iB] - tt[iB - 1])
            minutos = (tB - tA) / 60
            vel = (B - A) / 1000 / (minutos / 60) if minutos > 0 else 0
            if 3 <= vel <= 60:                       # descarta trayectorias imposibles
                filas.append((pd.Timestamp(int(tA), unit='s').hour, minutos))
        if filas:
            out[(r, dr)] = pd.DataFrame(filas, columns=['h', 'min'])
    dias = d[d.timestamp >= DENSO_DESDE].timestamp.dt.normalize().nunique()
    return out, dias


def programados(rd, REC, a_xy):
    """{(recorrido, sentido, hora): minutos} según el GTFS (días hábiles)."""
    trips = rd('trips.txt')
    trips = trips[trips.service_id == 'L'].copy()
    # sentido: la letra que sigue al recorrido en shape_id (712I, 712IPM -> I)
    trips['dir'] = [s_[len(r_):len(r_) + 1] if s_.startswith(r_) else s_[-1] for s_, r_ in zip(trips.shape_id, trips.route_id)]
    trips = trips[[(r, dr) in REC for r, dr in zip(trips.route_id, trips.dir)]]
    st = rd('stop_times.txt', usecols=['trip_id', 'arrival_time', 'stop_id', 'stop_sequence'])
    st = st[st.trip_id.isin(trips.trip_id)].copy()
    hms = lambda s: s.str.split(':', expand=True).astype(int).pipe(lambda x: x[0] * 3600 + x[1] * 60 + x[2])
    st['t'] = hms(st.arrival_time)
    st['seq'] = st.stop_sequence.astype(int)
    stops = rd('stops.txt')[['stop_id', 'stop_lat', 'stop_lon']]
    stops[['stop_lat', 'stop_lon']] = stops[['stop_lat', 'stop_lon']].astype(float)
    st = st.merge(stops, on='stop_id').merge(trips[['trip_id', 'route_id', 'dir']], on='trip_id')
    fq = rd('frequencies.txt')
    fq = fq[fq.trip_id.isin(trips.trip_id)].copy()
    fq['ini'] = hms(fq.start_time)
    fq['fin'] = hms(fq.end_time)
    fq = fq.groupby('trip_id')
    prog = {}
    for tid, s in st.groupby('trip_id'):
        r, dr = s.route_id.iloc[0], s.dir.iloc[0]
        L = REC[(r, dr)]['line']
        A, B = limites(L.length)
        s = s.sort_values('seq')
        ch = np.maximum.accumulate(shapely.line_locate_point(L, shapely.points(a_xy(s.stop_lon, s.stop_lat))))
        if ch[0] > A + 500 or ch[-1] < B - 500:
            continue                                  # variante que no cubre el tramo
        minutos = (np.interp(B, ch, s.t) - np.interp(A, ch, s.t)) / 60
        if tid not in fq.groups:
            continue
        for f in fq.get_group(tid).itertuples():
            for h in range(f.ini // 3600, (f.fin - 1) // 3600 + 1):
                prog.setdefault((r, dr, h % 24), []).append(minutos)
    return {k: float(np.median(v)) for k, v in prog.items()}


def resumen(REC, reales_, prog, limpio):
    """{(recorrido, sentido): {'km', 'desde', 'hasta', 'horas': [[h, n, mediana, p90, programado], ...]}}"""
    out = {}
    for (r, dr), R in REC.items():
        v = reales_.get((r, dr))
        filas = []
        for h in HORAS:
            x = v[v.h == h]['min'] if v is not None else pd.Series(dtype=float)
            p = prog.get((r, dr, h))
            if len(x) >= MIN_VIAJES:
                filas.append([h, int(len(x)), round(float(x.median())), round(float(x.quantile(0.9))),
                              None if p is None else round(p)])
            elif p is not None:
                filas.append([h, int(len(x)), None, None, round(p)])
        if not any(f[2] is not None for f in filas):
            continue
        A, B = limites(R['line'].length)
        s = R['stops']
        cerca = lambda km: limpio(s.stop_name.iloc[int(np.argmin(np.abs(R['ch'] - km)))])
        out[(r, dr)] = {'km': round((B - A) / 1000, 1), 'desde': cerca(A), 'hasta': cerca(B), 'horas': filas}
    return out
