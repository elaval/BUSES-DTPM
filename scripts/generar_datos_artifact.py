"""Genera data_vivo.json (flota de los últimos 7 días) para el dashboard artifact, leyendo la rama `data`. Uso: python scripts/generar_datos_artifact.py salida.json"""
import pandas as pd, json, sys, urllib.request
BASE='https://raw.githubusercontent.com/elaval/BUSES-DTPM/'
h=pd.read_parquet(BASE+'data/data/metricas_historicas.parquet')
ops=json.loads(urllib.request.urlopen(BASE+'main/data/operadores.json').read())
op=h[h.nivel=='operador'].copy()
fin=op.timestamp.max(); ini=fin-pd.Timedelta(days=7)
w=op[op.timestamp>ini]
agg=w.groupby('timestamp').agg(total=('total_buses','sum'),mov=('buses_en_movimiento','sum'),sin=('buses_sin_senal','sum'),nsin=('buses_sin_senal','count')).reset_index()
serie=[[t.strftime('%Y-%m-%dT%H:%M'),int(a),int(b),(int(c) if n>0 else None)] for t,a,b,c,n in zip(agg.timestamp,agg.total,agg.mov,agg.sin,agg.nsin)]
u=op[op.timestamp==fin]
ahora=[{'id':int(r.operador),'nombre':ops.get(str(int(r.operador)),f'Operador {r.operador}'),'total':int(r.total_buses),'mov':int(r.buses_en_movimiento),'sin':(None if pd.isna(r.buses_sin_senal) else int(r.buses_sin_senal))} for r in u.itertuples()]
# perfil horario dias habiles: ultimos 7 dias vs historico (mediana por hora)
t=op.groupby('timestamp').buses_en_movimiento.sum(); t=t[t.index.dayofweek<5]
hist=t.groupby(t.index.hour).median(); rec=t[t.index>ini]; rec=rec.groupby(rec.index.hour).median()
perfil=[{'h':int(k),'historico':int(hist.get(k,0)),'semana':(int(rec[k]) if k in rec else None)} for k in range(24)]
out={'actualizado':fin.strftime('%Y-%m-%dT%H:%M'),'capturas_7d':int(agg.shape[0]),'serie':serie,'ahora':ahora,'perfil':perfil}
json.dump(out,open(sys.argv[1] if len(sys.argv)>1 else 'data_vivo.json','w'),ensure_ascii=False,separators=(',',':'))
print('ok',out['actualizado'],len(serie))
