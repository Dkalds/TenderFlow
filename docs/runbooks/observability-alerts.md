# Runbook: Observability Alerts

**Propósito**: Diagnosticar y responder a alertas automáticas de TenderFlow.

**Responsable**: el mantenedor. (Este runbook decía «Equipo de Operaciones»;
no existe tal equipo y escribirlo así hacía que la alerta pareciera de alguien.)
**Última verificación contra el código**: 2026-09-03.

---

## Hay DOS planos de alerta, y hasta 2026-09-03 solo uno llegaba a un humano

Es lo primero que hay que saber al recibir —o al no recibir— una alerta.

### Plano A — `ops_events` + email (el que siempre funcionó)

Lo emite Python: `observability/alerts.py::notify`, llamado desde
`scheduler/healthcheck.py`, `scheduler/anomaly_alerts.py` y desde el fallo de
cualquier paso canónico (`scheduler/pipeline_runs.py::_notify_step_failure`).
Sale por SMTP a `ALERT_EMAIL_TO`. Es el único plano de los planos efímeros
(scraper, ML y pliegos en GitHub Actions), que no son scrapeables porque el
proceso muere al terminar el job.

Propiedad que hay que recordar: **`notify` nunca propaga**. Un buzón mal
configurado o un SMTP caído no tumban el job — pero tampoco se notaban. Desde
2026-09-03 el fallo de entrega incrementa `alert_delivery_failed_total`, así que
deja rastro.

Las alertas de la tabla de abajo son de este plano.

### Plano B — Prometheus + Alertmanager (cableado el 2026-09-03)

Lo emite `observability/alert_rules.yml` (10 reglas) evaluado por el Prometheus
de Render (ADR-019). **Hasta el 2026-09-03 este plano no llegaba a nadie**:
`prometheus.render.yml` no tenía bloque `alerting:` y no existía Alertmanager,
así que las alertas se disparaban dentro de Prometheus y morían en su página
`/alerts`. Las etiquetas `severity: critical` de `ApiErrorRateHigh` y
`PgPoolHealthCheckFailed` decoraban un enrutado inexistente.

Eso importa porque `ApiErrorRateHigh` se escribió justo después del incidente
del 2026-08-28 —la superficie pública devolviendo 500 durante horas sin que se
disparara nada—; con la regla escrita y sin receptor, ese incidente habría
vuelto a pasar igual.

Hoy: `observability/alertmanager.yml` enruta a email (las mismas variables
`ALERT_*`, no hay un segundo juego de credenciales) y, opcionalmente, a un
webhook (`ALERTMANAGER_WEBHOOK_URL`). El servicio es el `pserv`
`tenderflow-alertmanager` de `render.yaml`.

**La regla `Watchdog` dispara siempre, por diseño.** Si deja de llegar, lo que
falla es el canal —Prometheus, Alertmanager o el transporte— y por tanto
**ninguna otra alerta de este fichero podría llegar tampoco**. Verificar que
llega es la comprobación de salud del propio sistema de alertas.

> **Acción humana pendiente:** apuntar `ALERTMANAGER_WEBHOOK_URL` a un
> dead-man's-switch real (healthchecks.io, Better Stack, Cronitor). Sin eso, el
> Watchdog demuestra que Prometheus evalúa y que Alertmanager enruta, pero
> **nadie detecta el silencio**, que es justo la mitad que importa. Y no vale
> mandarlo al email: un Watchdog que llena el buzón cada 4 h se filtra en dos
> días y con él se pierde la señal.

### Qué mirar según lo que recibas

| Lo que pasa | Plano | Dónde mirar primero |
|---|---|---|
| Llega un email `[TenderFlow] [ERROR] …` | A | La tabla de abajo, por título de alerta |
| Llega un email de Alertmanager | B | `observability/alert_rules.yml`, la regla por `alertname` |
| **Deja de llegar el Watchdog** | B | El canal entero está caído: Prometheus, Alertmanager o SMTP. Nada de este fichero es fiable hasta arreglarlo |
| No llega nada y sospechás igual | ambos | `alert_delivery_failed_total` en `/metrics`, y `ops_events` en la BD |

---

## Alertas disponibles (plano A)

| Alerta | Nivel | Fuente | Umbral |
|---|---|---|---|
| Feed diario con lag | WARN | `check_daily_lag()` | > 8h sin actualización |
| Feed diario: fallos consecutivos | ERROR | `check_daily_consecutive_failures()` | 3 fallos seguidos |
| Modelo ML SAP obsoleto | WARN | `check_ml_model_staleness()` | > 30 días desde entrenamiento |
| Scheduler job timeout | ERROR | `scheduler/loop.py` | > 600s (configurable) |
| Scheduler job failure | ERROR | `scheduler/loop.py` | Excepción en ejecución |
| DB pool acquire timeout | ERROR | `db/connection.py` | > 10s sin conexión |

---

## 1. Feed diario con lag (> 8h)

**Síntoma**: Alerta "Feed diario con lag de Xh".

**Diagnóstico**:

```bash
python -c "
from db.database import get_cursor
from datetime import datetime, UTC
c = get_cursor('place_live_atom')
if c:
    last = c.get('last_seen_updated', 'N/A')
    print(f'Last updated: {last}')
    try:
        dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
        lag = (datetime.now(UTC) - dt).total_seconds() / 3600
        print(f'Lag: {lag:.1f}h')
    except: pass
else:
    print('No cursor found — scraper never ran')
"
```

**Causas comunes**:
1. Scraper no se ejecutó (workflow `scrape-daily.yml` falló)
2. PLACSP feed ATOM no tiene datos nuevos (normal fuera de horario laboral)
3. Timeout de red al descargar ZIPs

**Acción**:
```bash
# Re-ejecutar scraper manualmente
python -m scheduler.run_update

# Verificar estado del último run
python -c "
from db.database import connect
with connect() as c:
    rows = c.execute(
        'SELECT fuente, status, created_at FROM extraction_runs '
        'ORDER BY created_at DESC LIMIT 5'
    ).fetchall()
    for r in rows:
        print(f'  {r[0]:20s} {r[1]:10s} {r[2]}')
"
```

---

## 2. Feed diario: 3 fallos consecutivos

**Síntoma**: Alerta "Feed diario: 3 fallos consecutivos".

**Diagnóstico**:

```bash
python -c "
from services.extraction_runs import load_recent_daily_statuses
statuses = load_recent_daily_statuses(5)
print(f'Last 5 statuses: {statuses}')
"
```

**Causas comunes**:
1. PLACSP cambió la estructura del ATOM feed
2. Error de parseo XML (ver DLQ)
3. Timeout de red persistente

**Acción**:
```bash
# Ver errores en DLQ
python -c "
from db.database import connect
with connect() as c:
    rows = c.execute(
        'SELECT error_type, COUNT(*) as n, payload_ref '
        'FROM dlq WHERE scope=\'parse\' '
        'GROUP BY error_type, payload_ref ORDER BY n DESC LIMIT 10'
    ).fetchall()
    for r in rows:
        print(f'  {r[0]:20s} n={r[1]:4d}  ref={r[2]}')
"

# Reintentar extracciones fallidas
python -m scheduler.dlq_retry
```

---

## 3. Modelo ML SAP obsoleto (> 30 días)

**Síntoma**: Alerta "Modelo ML SAP obsoleto (X días)".

**Diagnóstico**:

```bash
python -c "
import joblib
from pathlib import Path
p = Path('models/sap_classifier.pkl')
if p.exists():
    clf = joblib.load(p)
    print(f'Trained at: {clf.metadata.get(\"trained_at\", \"unknown\")}')
    print(f'Model file: {p.stat().st_size} bytes')
else:
    print('Model file not found')
"
```

**Acción**:
```bash
# Re-entrenar modelo con datos recientes
python -m scraper.ml_training --force
```

---

## 4. Scheduler job timeout

**Síntoma**: Alerta "Scheduler job timeout: {name}".

**Diagnóstico**:

```bash
# Verificar jobs activos
python -c "
import psutil
for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    if 'scheduler' in str(p.info.get('cmdline', '')):
        print(f'  PID {p.pid}: {p.info[\"name\"]}')
"

# Verificar uso de recursos
docker stats --no-stream
```

**Causas comunes**:
1. Job pesado (daily_atom, recent_bulk) toma más de 600s
2. Proceso colgado por lock de BD
3. Memory pressure

**Acción**:
```bash
# Aumentar timeout temporalmente
export SCHEDULER_JOB_TIMEOUT_SECONDS=1200

# O reducir el trabajo
export SCHEDULER_BULK_MONTHS=1
```

---

## 5. Scheduler job failure

**Síntoma**: Alerta "Scheduler job fallo: {name}".

**Diagnóstico**:

```bash
# Ver logs recientes del scheduler
docker compose logs scheduler --tail=50

# Buscar errores específicos
docker compose logs scheduler 2>&1 | grep -i "error\|exception\|failed"
```

**Acción**:
```bash
# Re-ejecutar el job específico
python -c "from scheduler.jobs import build_default_registry; \
    [j.fn() for j in build_default_registry() if j.name == 'NOMBRE_JOB']"
```

---

## 6. DB pool acquire timeout

**Síntoma**: Alerta en logs: "db_pool_acquire_timeout".

**Diagnóstico**:

```bash
python -c "
from db.database import connect
with connect() as c:
    # Ver conexiones activas
    rows = c.execute('PRAGMA journal_mode').fetchall()
    print(f'Journal mode: {rows}')
    # Ver WAL size
    import os
    db_path = 'data/licitaciones.db'
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        size_mb = os.path.getsize(wal_path) / (1024*1024)
        print(f'WAL size: {size_mb:.1f} MB')
"
```

**Acción**:
```bash
# Forzar checkpoint WAL
python -c "
from db.database import connect
with connect() as c:
    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    print('WAL checkpoint done')
"

# Si persiste, reiniciar el servicio
docker compose restart api scheduler
```

---

## Notas generales

- Las alertas se envían por email si `ALERT_EMAIL_TO` y `ALERT_SMTP_*` están configurados.
- Si no hay SMTP configurado, las alertas solo aparecen en logs estructurados.
- El nivel mínimo de alerta se configura con `ALERT_MIN_LEVEL` (default: `warn`).
- Para suprimir una alerta específica, ajustar el umbral en `observability/alerts.py` o en las variables de entorno del scheduler.
