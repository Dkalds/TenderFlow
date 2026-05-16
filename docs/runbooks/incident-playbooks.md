# Runbooks de Incidentes — Licitaciones SAP

Playbooks de respuesta rápida para los incidentes más comunes del sistema.

---

## Índice

1. [Dashboard inaccesible](#1-dashboard-inaccesible)
2. [Scraper sin ejecutarse >36h](#2-scraper-sin-ejecutarse-36h)
3. [DLQ con >50 entradas sin resolver](#3-dlq-con-50-entradas-sin-resolver)
4. [Base de datos corrupta o inaccesible](#4-base-de-datos-corrupta-o-inaccesible)
5. [Caída de frescura de datos](#5-caída-de-frescura-de-datos)
6. [Errores de autenticación en cascada](#6-errores-de-autenticación-en-cascada)
7. [Uso excesivo de memoria del proceso Streamlit](#7-uso-excesivo-de-memoria-del-proceso-streamlit)
8. [Fallo de backup diario](#8-fallo-de-backup-diario)

---

## 1. Dashboard inaccesible

**Síntomas:** HTTP 5xx o timeout en la URL del dashboard. Alertas del healthcheck.

**Diagnóstico:**

```bash
# 1. Verificar que el proceso está en marcha
ps aux | grep streamlit

# 2. Ver logs recientes
tail -n 100 logs/streamlit.log  # o journalctl -u licitaciones-dashboard

# 3. Comprobar healthcheck interno
python -c "from scheduler.healthcheck import run_healthcheck; print(run_healthcheck())"
```

**Resolución:**

```bash
# Reiniciar el servicio
make restart  # o systemctl restart licitaciones-dashboard

# Si el problema persiste: revisar si la DB está bloqueada
python -c "from db.database import connect; print(connect().__enter__().execute('SELECT 1').fetchone())"
```

**Escalado:** Si el dashboard no vuelve en 10 minutos → notificar al equipo.

---

## 2. Scraper sin ejecutarse >36h

**Síntomas:** KPI "Antigüedad scrape" > 36h en el dashboard de Calidad de Datos.

**Diagnóstico:**

```bash
# Ver últimos runs
python -c "
from db.database import connect
rows = connect().__enter__().execute(
    'SELECT run_id, started_at, status, errores_parseo FROM extraction_runs ORDER BY started_at DESC LIMIT 5'
).fetchall()
for r in rows: print(r)
"

# Ver DLQ
python -c "from db.dlq import list_unresolved; [print(f) for f in list_unresolved(10)]"
```

**Resolución:**

```bash
# Ejecutar scraping manual
python scheduler/run_update.py --once

# O via make
make scrape

# Verificar que el scheduler sigue programado (Windows Task Scheduler / cron)
# Windows:
schtasks /query /tn "LicitacionesSAP_Daily"
# Linux:
crontab -l | grep licitaciones
```

**Escalado:** Si falla 3 veces consecutivas → revisar conectividad con PLACSP y variables de entorno.

---

## 3. DLQ con >50 entradas sin resolver

**Síntomas:** KPI "DLQ sin resolver" > 50 en Calidad de Datos, o alerta automática.

**Diagnóstico:**

```bash
python -c "
from db.dlq import unresolved_summary
for r in unresolved_summary():
    print(r)
"
```

**Resolución:**

```bash
# Opción 1: Reintentar automáticamente via DLQ retry
python -c "from scheduler.dlq_retry import retry_failed_extractions; print(retry_failed_extractions())"

# Opción 2: Marcar como resueltos los fallos de una fuente específica (si son transitorios)
python -c "from db.dlq import mark_matching_resolved; print(mark_matching_resolved('bulk_202401'))"

# Opción 3: Panel Admin → pestaña DLQ → marcar resueltos
```

**Causa habitual:** PLACSP devuelve HTTP 503 durante mantenimiento — los fallos se resuelven solos al reintentar.

---

## 4. Base de datos corrupta o inaccesible

**Síntomas:** Errores SQLite en logs (`database disk image is malformed`, `SQLITE_BUSY`).

**Diagnóstico:**

```bash
python -c "
import sqlite3
from config import settings
conn = sqlite3.connect(str(settings.DATABASE_PATH))
print(conn.execute('PRAGMA integrity_check').fetchall())
"
```

**Resolución — DB corrupta:**

```bash
# 1. Detener todos los procesos que usan la DB
make stop

# 2. Restaurar desde el backup más reciente
ls -la data/backups/
# O desde S3: aws s3 ls s3://$BACKUP_S3_BUCKET/backups/ --endpoint-url $AWS_ENDPOINT_URL
gunzip -c data/backups/licitaciones_YYYYMMDD_HHMMSS.db.gz > data/licitaciones_restored.db
mv data/licitaciones.db data/licitaciones_corrupted.db.bak
mv data/licitaciones_restored.db data/licitaciones.db

# 3. Verificar integridad
python -c "import sqlite3; print(sqlite3.connect('data/licitaciones.db').execute('PRAGMA integrity_check').fetchall())"

# 4. Reiniciar servicios
make start
```

**Resolución — SQLITE_BUSY:**

```bash
# Identificar procesos con la DB abierta
fuser data/*.db  # Linux
# Si hay procesos zombie: reiniciar y esperar el timeout (5 minutos por defecto)
```

---

## 5. Caída de frescura de datos

**Síntomas:** Datos del dashboard parecen no actualizarse aunque el scraper ejecuta.

**Diagnóstico:**

```bash
# ¿Se invalidó la caché?
python -c "
from shared.cache_signal import read_signal_timestamp
import time
print(f'Señal: {read_signal_timestamp()}, ahora: {time.time()}')
"

# ¿Cuántos registros hay en la DB?
python -c "
from db.database import connect
print(connect().__enter__().execute('SELECT COUNT(*), MAX(fecha_publicacion) FROM licitaciones').fetchone())
"
```

**Resolución:**

```bash
# Forzar invalidación de caché del dashboard (crea el fichero de señal)
python -c "from shared.cache_signal import write_cache_signal; write_cache_signal()"

# Si la app está en ejecución, también se puede usar el endpoint admin
# → Dashboard → Observabilidad → "Invalidar caché"
```

---

## 6. Errores de autenticación en cascada

**Síntomas:** Múltiples usuarios reportan no poder iniciar sesión. Logs con `login_lockout_triggered`.

**Diagnóstico:**

```bash
# Ver access_log reciente
python -c "
from db.database import connect
rows = connect().__enter__().execute(
    'SELECT email, auth_method, logged_in_at FROM access_log ORDER BY logged_in_at DESC LIMIT 20'
).fetchall()
for r in rows: print(r)
"

# Ver rate_limits activos
python -c "
from db.database import connect
import time
rows = connect().__enter__().execute(
    'SELECT key, COUNT(*) FROM rate_limits WHERE ts > ? GROUP BY key ORDER BY 2 DESC',
    (time.time() - 3600,)
).fetchall()
for r in rows: print(r)
"
```

**Resolución:**

```bash
# Si es un ataque de fuerza bruta legítimo → rate_limits se limpian solos tras la ventana
# Si es un falso positivo (todos los usuarios bloqueados):
python -c "
from db.database import connect
import time
# Limpiar ventana de 1 hora
c = connect().__enter__()
c.execute('DELETE FROM rate_limits WHERE ts < ?', (time.time() - 3600,))
print('Limpiado')
"
```

---

## 7. Uso excesivo de memoria del proceso Streamlit

**Síntomas:** El proceso Streamlit ocupa >2 GB RAM, respuestas lentas o OOM.

**Diagnóstico:**

```bash
# Ver uso de memoria del proceso
ps aux | grep streamlit
# O con psutil:
python -c "import psutil, os; p = psutil.Process(os.getpid()); print(p.memory_info())"

# Cuántos objetos en caché
python -c "from dashboard.data_loader import _load_dataframe_shared; print(_load_dataframe_shared.cache_info())" 2>/dev/null || echo "No disponible"
```

**Resolución:**

```bash
# 1. Invalidar caches manualmente
python -c "from dashboard.data_loader import invalidate_caches; invalidate_caches()"

# 2. Si el problema persiste, reiniciar el proceso
make restart

# 3. Verificar que DASHBOARD_CACHE_TTL está configurado (default: sin TTL = cache indefinida)
python -c "from config import settings; print(settings.DASHBOARD_CACHE_TTL)"
```

**Preventivo:** Configurar `DASHBOARD_CACHE_TTL=3600` en `.env` para limitar la vida de la caché.

---

## 8. Fallo de backup diario

**Síntomas:** GitHub Actions workflow `backup.yml` falla, o no hay backups nuevos en S3.

**Diagnóstico:**

```bash
# Ver últimos backups locales
ls -la data/backups/

# Ver si hay backups en S3
aws s3 ls s3://$BACKUP_S3_BUCKET/backups/ --endpoint-url $AWS_ENDPOINT_URL | tail -10

# Ejecutar backup manual para diagnosticar
python scripts/backup_db.py --dry-run --s3
```

**Resolución:**

```bash
# Backup manual sin S3 (solo local)
python scripts/backup_db.py --keep 7

# Backup manual con S3
BACKUP_S3_BUCKET=mi-bucket python scripts/backup_db.py --s3 --keep 3 --keep-s3 30
```

**Causas habituales:**
- Credenciales S3 expiradas → rotar `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` en GitHub Secrets
- `BACKUP_S3_BUCKET` no configurado → verificar secrets del repositorio
- DB no encontrada en el runner → configurar `DATABASE_PATH` o montar volumen

---

## Contactos de escalado

| Nivel | Acción | Tiempo máximo respuesta |
|-------|--------|------------------------|
| L1 — Auto-remediación | Scheduler reintentos DLQ | 30 min |
| L2 — Operaciones | Ejecutar runbook manual | 2h |
| L3 — Ingeniería | Investigar causa raíz | 1 día hábil |
