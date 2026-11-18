"""
Asigna un recorrido público a los códigos de servicio del GPS que no están en el
archivo oficial de equivalencias (docs/Servicios_decos_*.xlsx).

Desde la crisis de Metropol (oct-2026) otros operadores cubren recorridos con
códigos nuevos (p. ej. T1998 opera la 712, que antes era T967). Sin esta
corrección, esos datos no cuentan para su recorrido.

Paso 1, formato: el GPS ahora escribe las variantes pegadas al número ("T506e1",
"T411c") y el Excel con espacio ("T506 E1", "T411 C0"). Se normalizan y se buscan en
el Excel. (Verificado: en los 28 casos con datos suficientes, el trazado confirma
la misma asignación.)

Paso 2, trazado: para cada código que siga sin equivalencia y cada sentido, se
toman posiciones recientes de buses en movimiento y se comparan con los trazados
del GTFS:
  - precisión: fracción de las posiciones a menos de 50 m del trazado
  - cobertura: fracción del trazado (puntos cada 200 m) con alguna posición a menos de 75 m
Gana el recorrido con mayor puntaje (media armónica de ambas). Un sentido "coincide"
si la precisión es ≥ 85 %, la cobertura ≥ 70 % y no hay otro recorrido casi igual
de bueno (p. ej. un expreso por las mismas calles que el normal: queda "ambiguo").
El código se asigna si al menos un sentido coincide y todos sus sentidos apuntan
al mismo recorrido con precisión ≥ 75 % y cobertura ≥ 60 % (tolera desvíos).
El número interno del código no sirve de pista: T1411 es la 401 y T411c la 211c.
"""
import re

import numpy as np
import pandas as pd
import shapely

PREC_MIN, COB_MIN, EMPATE = 0.85, 0.70, 0.03
PREC_OTRO, COB_OTRO = 0.75, 0.60                     # para el otro sentido del mismo código
DIST_PREC, DIST_COB, PASO_COB = 50, 75, 200        # metros
MIN_REGISTROS, MAX_MUESTRA, DIAS = 200, 2000, 21


def _dir(shape_id, route_id):
    """Sentido del trazado: la letra que sigue al recorrido en shape_id (712IPM -> I)."""
    resto = shape_id[len(route_id):] if shape_id.startswith(route_id) else shape_id[-1]
    return resto[:1] if resto[:1] in ('I', 'R') else None


def normalizar(codigo):
    """'T506e1' -> 'T506 E1', 'T411c' -> 'T411 C0'; None si no tiene ese formato."""
    m = re.fullmatch(r'(T\d+)([cevn])(\d?)', str(codigo))
    return f'{m[1]} {m[2].upper()}{m[3] or "0"}' if m else None


def por_formato(codigos, srv2pub):
    """Códigos del GPS que están en el Excel con otro formato: {codigo: recorrido}."""
    return {c: srv2pub[n] for c in codigos if c not in srv2pub and (n := normalizar(c)) in srv2pub}


def inferir(hab, srv2pub, trips, shapes_geo, a_xy):
    """hab: GPS (timestamp, servicio, sentido, estado, latitud, longitud).
    trips: trips.txt del GTFS (route_id, shape_id). shapes_geo: {shape_id: LineString en metros}.
    Devuelve ({codigo: recorrido}, informe por código y sentido)."""
    d = hab[(hab.timestamp >= hab.timestamp.max() - pd.Timedelta(days=DIAS)) & (hab.estado == 'en_movimiento')]
    d = d[d.servicio.notna() & ~d.servicio.isin(srv2pub) & ~d.servicio.str.endswith('TS') & d.sentido.isin(['I', 'R'])]
    if d.empty:
        return {}, []

    cand = trips[['route_id', 'shape_id']].drop_duplicates()
    cand = cand[cand.shape_id.isin(shapes_geo)].assign(dir=lambda c: [_dir(s, r) for s, r in zip(c.shape_id, c.route_id)])
    cand = cand.dropna(subset=['dir']).reset_index(drop=True)
    geoms = [shapes_geo[s] for s in cand.shape_id]
    arbol = shapely.STRtree(geoms)
    muestras_trazado = [shapely.points([g.interpolate(x).coords[0] for x in np.arange(0, g.length, PASO_COB)]) for g in geoms]

    informe = []
    for (srv, sen), g in d.groupby(['servicio', 'sentido']):
        if len(g) < MIN_REGISTROS:
            continue
        g = g.sample(min(len(g), MAX_MUESTRA), random_state=0)
        P = shapely.points(a_xy(g.longitud, g.latitud))
        ip, ig = arbol.query(P, predicate='dwithin', distance=DIST_PREC)
        prec = pd.Series(ip).groupby(ig).nunique() / len(P)            # por trazado
        top = prec.sort_values(ascending=False).head(6)
        arbol_p = shapely.STRtree(P)
        res = []
        for gi, pr in top.items():
            m = muestras_trazado[gi]
            cub = len(np.unique(arbol_p.query(m, predicate='dwithin', distance=DIST_COB)[0])) / max(len(m), 1)
            f = 2 * pr * cub / (pr + cub) if pr + cub else 0
            res.append((f, pr, cub, cand.route_id[gi], cand.dir[gi]))
        res.sort(reverse=True)
        if not res:
            continue
        # mejor por recorrido (un recorrido puede tener varios trazados)
        por_ruta = {}
        for r_ in res:
            por_ruta.setdefault(r_[3], r_)
        orden = sorted(por_ruta.values(), reverse=True)
        mejor, segundo = orden[0], (orden[1] if len(orden) > 1 else None)
        estado = 'asignado'
        if mejor[1] < PREC_MIN or mejor[2] < COB_MIN:
            estado = 'sin coincidencia suficiente'
        elif segundo and mejor[0] - segundo[0] < EMPATE:
            estado = 'ambiguo'
        informe.append({'codigo': srv, 'sentido': sen, 'registros': len(g), 'recorrido': mejor[3],
                        'sentido_trazado': mejor[4], 'precision': round(mejor[1], 2), 'cobertura': round(mejor[2], 2),
                        'segundo': (segundo[3] if segundo else None), 'estado': estado})

    # un código se asigna si sus sentidos con datos coinciden en el recorrido
    asignados = {}
    inf = pd.DataFrame(informe)
    if not inf.empty:
        for srv, g in inf.groupby('codigo'):
            if ((g.estado == 'asignado').any() and not (g.estado == 'ambiguo').any() and g.recorrido.nunique() == 1
                    and (g.precision >= PREC_OTRO).all() and (g.cobertura >= COB_OTRO).all()):
                asignados[srv] = g.recorrido.iloc[0]
    return asignados, informe


def operador_actual(hab, srv2pub, nombres, dias=DIAS, minimo=MIN_REGISTROS):
    """Operador que hoy opera cada recorrido, según el GPS reciente (puede diferir del Excel)."""
    d = hab[hab.timestamp >= hab.timestamp.max() - pd.Timedelta(days=dias)]
    d = d.assign(pub=d.servicio.map(srv2pub)).dropna(subset=['pub', 'operador'])
    c = d.groupby(['pub', 'operador']).size().reset_index(name='n').sort_values('n', ascending=False)
    c = c[c.n >= minimo].drop_duplicates('pub')
    return {p: re.sub(r'^U\d+ - ', '', nombres.get(str(int(o)), '')) for p, o in zip(c.pub, c.operador) if nombres.get(str(int(o)))}
