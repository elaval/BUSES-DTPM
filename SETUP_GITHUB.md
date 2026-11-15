# Configuración de GitHub Actions

## 🔐 Configurar GitHub Secrets (Credenciales Seguras)

Las credenciales de la API DTPM se almacenan de forma **encriptada** en GitHub. Nadie puede verlas, ni siquiera los colaboradores del repositorio.

### Paso 1: Ir a la configuración de Secrets

1. Ve a tu repositorio en GitHub
2. Click en **Settings** (Configuración)
3. En el menú lateral izquierdo, busca **Secrets and variables** → **Actions**
4. Click en el botón verde **"New repository secret"**

### Paso 2: Agregar el primer secret

1. **Name**: `DTPM_USUARIO`
2. **Secret**: Pega tu usuario de la API DTPM (el mismo que tienes en `.env`)
3. Click en **"Add secret"**

### Paso 3: Agregar el segundo secret

1. Click nuevamente en **"New repository secret"**
2. **Name**: `DTPM_CLAVE`
3. **Secret**: Pega tu contraseña de la API DTPM
4. Click en **"Add secret"**

### Paso 4: Habilitar permisos de escritura para GitHub Actions

GitHub Actions necesita permiso para hacer commits automáticos con los datos capturados.

1. En **Settings** → **Actions** → **General**
2. Scroll hasta **"Workflow permissions"**
3. Selecciona **"Read and write permissions"**
4. Marca la casilla **"Allow GitHub Actions to create and approve pull requests"** (opcional)
5. Click en **"Save"**

## ✅ Verificación

Una vez configurado, el workflow se ejecutará automáticamente:

### Ejecución Automática
- **Cada 10 minutos** según el cron schedule
- Los datos se guardarán automáticamente en `data/*.parquet`
- GitHub Actions hará commits automáticos con el mensaje `📊 Update metrics: YYYY-MM-DD HH:MM UTC`

### Ejecución Manual (para probar)
1. Ve a **Actions** en tu repositorio
2. Click en **"Monitor Flota DTPM"** (workflow name)
3. Click en **"Run workflow"** → **"Run workflow"**
4. Espera 1-2 minutos y verifica los logs

## 🔍 Monitorear Ejecuciones

### Ver estado de workflows
```bash
gh run list --workflow=monitor.yaml --limit 10
```

### Ver logs de última ejecución
```bash
gh run view --log
```

### Ver logs de ejecución específica
```bash
gh run view <run_id> --log
```

## 🔒 Seguridad

### ✅ Es seguro porque:
- Los secrets están **encriptados** en GitHub
- No aparecen en logs ni en el código
- Solo GitHub Actions puede leerlos durante la ejecución
- Si alguien hace fork del repo, NO obtiene los secrets
- Puedes revocar/cambiar los secrets en cualquier momento

### ❌ NUNCA hagas esto:
```bash
# ❌ NO hacer esto
echo $DTPM_USUARIO  # No imprimas secrets en logs
```

### ✅ Buenas prácticas:
```bash
# ✅ Hacer esto
if [ -z "$DTPM_USUARIO" ]; then
  echo "Error: DTPM_USUARIO no está configurado"
  exit 1
fi
```

## 📊 Estructura de Commits Automáticos

GitHub Actions hará commits con este formato:

```
📊 Update metrics: 2026-05-08 15:45 UTC

Author: github-actions[bot]
```

Estos commits incluirán:
- `data/metricas_historicas.parquet` (crece indefinidamente)
- `data/datos_recientes.parquet` (tamaño fijo, últimas 2 horas)

## 🚨 Troubleshooting

### Error: "Resource not accessible by integration"
**Causa**: GitHub Actions no tiene permisos de escritura
**Solución**: Habilita "Read and write permissions" (Paso 4 arriba)

### Error: Authentication failed
**Causa**: Los secrets no están configurados correctamente
**Solución**: Verifica que los nombres sean exactamente `DTPM_USUARIO` y `DTPM_CLAVE`

### El workflow no se ejecuta cada 10 minutos
**Causa**: GitHub puede retrasar cron schedules en repos con poco uso
**Solución**: Los primeros días puede haber retrasos de 3-5 minutos, es normal

### Error: "fatal: not a git repository"
**Causa**: El directorio `data/` no existe
**Solución**: El script crea automáticamente la carpeta, pero puedes crearla manualmente con `mkdir data`

## 📈 Dashboard en Vivo

Para ver el dashboard en tiempo real con los datos capturados:

```bash
# En tu máquina local
git pull origin main  # Descargar últimos datos
source venv/bin/activate
streamlit run dashboard.py
```

O puedes desplegarlo en Streamlit Cloud para acceso público:
https://streamlit.io/cloud

---

**¿Preguntas?** Revisa el archivo [claude.md](claude.md) para más detalles técnicos.
