# Runbooks de Incidentes — Licitaciones SAP

Playbooks de respuesta rápida para los incidentes más comunes del sistema.

---

## Índice

1. [Frontend web inaccesible](#1-frontend-web-inaccesible)
2. [Scraper sin ejecutarse >36h](#2-scraper-sin-ejecutarse-36h)
3. [DLQ con >50 entradas sin resolver](#3-dlq-con-50-entradas-sin-resolver)
4. [Base de datos corrupta o inaccesible](#4-base-de-datos-corrupta-o-inaccesible)
5. [Caída de frescura de datos](#5-caída-de-frescura-de-datos)
6. [Errores de autenticación en cascada](#6-errores-de-autenticación-en-cascada)
7. [Enlace firmado filtrado](#7-enlace-firmado-filtrado-calendario-ics-o-baja-de-correos)

---

## 1. Frontend web inaccesible

**Síntomas:** HTTP 5xx o timeout en la URL del frontend web. Alertas del healthcheck.

**Diagnóstico:**

```bash
# 1. Verificar que el servicio está en marcha
docker compose ps web

# 2. Ver logs recientes
docker compose logs web --tail 100  # local; en producción, Vercel → Runtime Logs

# 3. Comprobar healthcheck interno
curl -fsS http://localhost:3000/ > /dev/null
```

**Resolución:**

```bash
# Reiniciar el servicio
docker compose restart web  # local; en producción, Vercel → Redeploy

# Si el problema persiste: revisar si la API responde
curl -fsS http://localhost:8080/api/v1/health/ready
```

**Escalado:** Si el frontend web no vuelve en 10 minutos → notificar al equipo.

---

## 2. Scraper sin ejecutarse >36h

**Síntomas:** KPI "Antigüedad scrape" > 36h en el panel de Calidad de Datos.

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

Producción corre sobre Supabase Postgres (ADR-016); SQLite se retiró en
ADR-021. Diagnóstico y restauración (backups gestionados por Supabase) en
[disaster-recovery.md](disaster-recovery.md) §0 y §2.

---

## 5. Caída de frescura de datos

**Síntomas:** Datos del frontend web parecen no actualizarse aunque el scraper ejecuta.

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
# Forzar invalidación de caché de la aplicación (crea el fichero de señal)
python -c "from shared.cache_signal import write_cache_signal; write_cache_signal()"

# Si la app está en ejecución, también se puede usar la acción
# de observabilidad para invalidar la caché
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

## 7. Enlace firmado filtrado (calendario ICS o baja de correos)

**Síntoma:** una persona reporta que su URL de suscripción al calendario, o el
enlace de baja del pie de un digest, ha llegado a alguien que no debía (chat
reenviado, calendario compartido, captura de pantalla).

**Qué expone:** el del calendario devuelve solo fechas de compromisos (plazos
de pursuits abiertos y de favoritos) de esa persona; el de baja pausa sus
reglas de watchlist, que se reactivan desde Mi Watchlist. Ninguno abre sesión
ni lee el corpus (RFC
[2026-09-02-enlaces-firmados](../rfc/2026-09-02-rfc-enlaces-firmados-sin-sesion.md)).

**Remedio:** los enlaces van firmados con `shared/signing`, así que se revocan
rotando la clave activa. La rotación es **global**: invalida todos los enlaces
emitidos con la clave retirada, de todos los usuarios, que volverán a pedir el
suyo desde Mi Pipeline.

1. Generar clave nueva: `python -c "import secrets; print(secrets.token_hex(32))"`.
2. En Render, añadir el `kid` nuevo a `SIGNING_KEYS_JSON` y apuntar
   `SIGNING_KEY_ACTIVE` a él, **sin borrar todavía** la clave anterior: así los
   tokens CSRF/OAuth en vuelo siguen verificando durante el despliegue.
3. Redesplegar. Comprobar que `GET /exports/calendario/enlace` devuelve una firma
   con el `kid` nuevo.
4. Retirar el `kid` viejo de `SIGNING_KEYS_JSON` y redesplegar: ese es el paso
   que invalida el enlace filtrado.

**Ojo:** `SIGNING_KEY` (variable única, legacy) sigue funcionando como fallback
si `SIGNING_KEYS_JSON` está vacía. Rotar solo esa variable invalida de golpe
CSRF, OAuth y estos enlaces sin periodo de gracia.

---

## Contactos de escalado

| Nivel | Acción | Tiempo máximo respuesta |
|-------|--------|------------------------|
| L1 — Auto-remediación | Scheduler reintentos DLQ | 30 min |
| L2 — Operaciones | Ejecutar runbook manual | 2h |
| L3 — Ingeniería | Investigar causa raíz | 1 día hábil |
