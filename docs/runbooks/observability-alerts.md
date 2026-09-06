# Runbook: alertas de observabilidad

**Propósito**: saber qué alertas existen, por dónde sale cada una, y qué hacer
cuando llega —o cuando deja de llegar—.

**Responsable**: el mantenedor. (Este runbook decía «Equipo de Operaciones»;
no existe tal equipo y escribirlo así hacía que la alerta pareciera de alguien.)

**Última verificación contra el repositorio**: 2026-09-06 (O0.3 del plan de
arquitectura v2). Todo lo que sigue se contrastó leyendo
`observability/alert_rules.yml`, `observability/alertmanager.yml`,
`observability/prometheus.render.yml`, `observability/alerts.py`,
`docker/Dockerfile.alertmanager` y `render.yaml`. **No se contrastó contra
Render**: desde el repositorio no se puede ver qué servicios existen ni qué
correos salieron. Lo que dependa del dashboard va marcado como acción humana
pendiente y no se da por hecho.

---

## 1. Hay DOS planos de alerta

Es lo primero que hay que saber al recibir —o al no recibir— una alerta.

### Plano A — `ops_events` + email (el que siempre funcionó)

Lo emite Python: `observability/alerts.py::notify`. Sus llamantes están
repartidos por `scheduler/` y `services/` —`healthcheck.py`, `anomaly_alerts.py`,
`competitor_alerts.py`, `concept_drift.py`, `drift_monitor.py`, `dlq_retry.py`,
`loop.py` (timeout y fallo de job), `jobs/ml_predicciones.py`,
`services/ml/drift.py`, `services/ml/calibration.py`, el fallo de cualquier paso
canónico (`scheduler/pipeline_runs.py::_notify_step_failure`) y hasta dos
workflows que lo invocan en línea (`security.yml`, `mutation-sample.yml`)—, así
que esta enumeración envejece: la lista viva se saca con

```bash
grep -rn "observability.alerts import\|notify(" --include=*.py --include=*.yml .
```

Sale por SMTP a `ALERT_EMAIL_TO`, filtrado por `ALERT_MIN_LEVEL` (default
`warn`). Es el **único** plano de los planos efímeros (scraper, ML y pliegos en
GitHub Actions): esos procesos mueren al terminar el job y Prometheus no puede
scrapearlos.

Propiedad que hay que recordar: **`notify` nunca propaga**. Un buzón mal
configurado o un SMTP caído no tumban el job — pero tampoco se notaban. Desde
2026-09-03 cada camino de fallo incrementa `alert_delivery_failed_total`
(`observability/alerts.py::_contar_fallo_entrega`), así que deja rastro
agregable; ver §4, incluida su limitación.

### Plano B — Prometheus + Alertmanager

Lo emite `observability/alert_rules.yml`, evaluado cada 30 s por el Prometheus
de Render (ADR-019, `observability/prometheus.render.yml`).

**Hasta el 2026-09-03 este plano no llegaba a nadie**: `prometheus.render.yml`
no tenía bloque `alerting:` y no había Alertmanager en ningún sitio del repo,
así que las alertas se disparaban dentro de Prometheus y morían en su página
`/alerts`. Las etiquetas `severity: critical` de `ApiErrorRateHigh` y
`PgPoolHealthCheckFailed` decoraban un enrutado inexistente. Eso importa porque
`ApiErrorRateHigh` se escribió justo después del incidente del 2026-08-28 —la
superficie pública devolviendo 500 durante horas sin que se disparara nada—:
con la regla escrita y sin receptor, ese incidente habría vuelto a pasar igual.

**Estado a 2026-09-06.** En el repositorio el plano está entero:
`prometheus.render.yml` enruta a `tenderflow-alertmanager:9093`,
`observability/alertmanager.yml` define el enrutado y los receptores, y
`render.yaml` declara el `pserv`. Lo que **no** está verificado es que el
servicio exista en Render: el Blueprint todavía no está vinculado (checklist de
la cabecera de `render.yaml`), así que declarar el servicio ahí no lo crea. El
alta manual es el checklist de §5. **Mientras ese checklist no esté hecho, el
plano B sigue sin receptor.**

---

## 2. Las diez reglas y por dónde sale cada una

`observability/alert_rules.yml` define **10 reglas en 5 grupos** (conteo del
2026-09-06). El enrutado sale de `observability/alertmanager.yml`: receptor por
defecto `email`; el `Watchdog` se desvía a `webhook` y corta (`continue:
false`); `severity = critical` casa dos rutas seguidas (`continue: true`), así
que va a los dos canales; y todo lo demás cae al receptor por defecto.

| Regla | Grupo | `severity` | Email | Webhook |
|---|---|---|---|---|
| `Watchdog` | `meta` | `none` | no | **sí** |
| `ApiErrorRateHigh` | `api_availability` | `critical` | sí | sí |
| `PgPoolHealthCheckFailed` | `postgres_pool_alerts` | `critical` | sí | sí |
| `LLMBudgetExceeded` | `llm_budget` | `warning` | sí | no |
| `DedupeMatchRateHigh` | `dedupe_quality` | `warning` | sí | no |
| `DedupeConfirmedBurst` | `dedupe_quality` | `warning` | sí | no |
| `PgPoolAcquireTimeoutHigh` | `postgres_pool_alerts` | `warning` | sí | no |
| `PgWriteLatencyHigh` | `postgres_pool_alerts` | `warning` | sí | no |
| `PgReadLatencyHigh` | `postgres_pool_alerts` | `warning` | sí | no |
| `PgConcurrentWritersHigh` | `postgres_pool_alerts` | `warning` | sí | no |

Nueve de las diez llegan al correo; el `Watchdog` es la única que no, y a
propósito (§3). Dos —las `critical`— llegan por los dos canales, que es lo que
hace que un incidente grave no dependa de un solo transporte.

Ritmo del correo (`route` de `alertmanager.yml`): agrupado por `alertname` +
`severity`, `group_wait` 30 s, `group_interval` 5 m y `repeat_interval` **4 h**
mientras la alerta siga viva. Una caída que dispara `ApiErrorRateHigh` y
`PgPoolHealthCheckFailed` a la vez manda dos correos, no veinte.

Silenciado por causa (`inhibit_rules`): con `PgPoolHealthCheckFailed` activa se
inhiben las demás `warning|critical` del mismo `env` (menos ella misma y el
`Watchdog`). Si la API no responde al scrape, la latencia y los 5xx son
consecuencia, no causa.

---

## 3. Comprobar que el `Watchdog` llega

`Watchdog` (`expr: vector(1)`, sin `for`) **dispara siempre, por diseño**. Su
valor no está en recibirla sino en **notar su ausencia**: si deja de llegar, lo
que falla es el canal —Prometheus, Alertmanager o el transporte— y por tanto
ninguna otra regla de este fichero podría llegar tampoco. Es la única
comprobación de salud del propio sistema de alertas.

Va al receptor `webhook` con `group_wait: 0s` y `repeat_interval: 1m`: una
notificación por minuto. Al correo no va —un Watchdog que llena el buzón cada 4
horas se filtra en dos días y con él se pierde la señal—.

Cómo comprobarlo, de menos a más externo:

1. **Logs del servicio** (Render → `tenderflow-alertmanager` → Logs). Con el
   webhook sin configurar, el entrypoint apunta el receptor a
   `http://127.0.0.1:9099/alertmanager-webhook-no-configurado` y el log muestra
   un fallo de entrega **de ese receptor** cada minuto. Eso ya demuestra media
   cadena: Prometheus evalúa la regla y Alertmanager la recibe y la enruta.
2. **Estado en Alertmanager**, desde otro servicio de la red privada de Render
   (el `pserv` no está expuesto a internet):

   ```bash
   curl -s http://tenderflow-alertmanager:9093/api/v2/alerts \
     | python -c "import json,sys; print([a['labels']['alertname'] for a in json.load(sys.stdin)])"
   ```

   `Watchdog` tiene que estar en la lista.
3. **Dead-man's-switch externo** (lo único que cierra la otra mitad). Con
   `ALERTMANAGER_WEBHOOK_URL` apuntando a healthchecks.io, Better Stack o
   Cronitor, su panel muestra un ping por minuto y **avisa cuando dejan de
   llegar**. Configurar el periodo de gracia por encima del minuto del
   `repeat_interval` para que un redeploy no dispare un falso positivo.

> **Acción humana pendiente (2026-09-06):** apuntar `ALERTMANAGER_WEBHOOK_URL` a
> un dead-man's-switch real. Sin eso, el Watchdog demuestra que Prometheus
> evalúa y que Alertmanager enruta, pero **nadie detecta el silencio**, que es
> justo la mitad que importa.

Criterio de aceptación de O0.3: el `Watchdog` llega al receptor en cada
intervalo durante **siete días seguidos**. Es una comprobación en producción, y
a fecha de este runbook no se ha hecho.

---

## 4. `alert_delivery_failed_total`: dónde se mira

Counter de `observability/runtime_metrics.py`, con etiquetas `canal`
(`email`) y `motivo` (`not_configured` · `smtp` · `network`). Sube cada vez que
una alerta del **plano A** no consigue salir del proceso.

Dónde se ve, hoy: **en ninguna panel de Grafana**. Los tres dashboards del repo
(`api_red.json`, `slo.json`, `provisioning/dashboards/scraper.json`) no lo
pintan, comprobado el 2026-09-06. Hasta que exista un panel, se consulta en
Grafana → **Explore** → datasource Prometheus:

```promql
# ¿Ha fallado alguna entrega en las últimas 24 h?
increase(alert_delivery_failed_total[24h])

# Desglose por motivo, que es lo que dice qué arreglar
sum by (motivo) (increase(alert_delivery_failed_total[24h]))
```

O directamente sobre `/metrics` de la API — **sin** prefijo `/api/v1`, que es la
ruta que scrapea Prometheus (`api/app.py`), y con una API key de scope
`metrics:read`:

```bash
curl -s -H "X-API-Key: $SMOKE_API_KEY" "$SMOKE_BASE_URL/metrics" \
  | grep alert_delivery_failed_total
```

Interpretación de los motivos:

| `motivo` | Qué pasó | Qué hacer |
|---|---|---|
| `not_configured` | Falta `ALERT_EMAIL_TO`, `ALERT_SMTP_USER` o `ALERT_SMTP_PASSWORD` | Completar las variables en el entorno del proceso que alerta |
| `smtp` | El servidor rechazó el envío (credencial caducada, App Password revocada) | Regenerar el App Password (docs/SECURITY.md, rotación 90 días) |
| `network` | No se pudo abrir la conexión SMTP | Red o `ALERT_SMTP_HOST`/`ALERT_SMTP_PORT` |

**Limitación que hay que tener presente**: el counter solo es scrapeable en el
proceso de la API. Los planos efímeros (scraper, ML, pliegos, `healthcheck.yml`
en GitHub Actions) son justamente los que más alertas envían y **su contador
muere con el job**: ahí el único rastro es el log estructurado del run y la
tabla `ops_events`. Un cero en Grafana significa «la API no falló entregas», no
«todas las alertas del proyecto llegaron».

---

## 5. Alta del Alertmanager en Render (checklist humano)

Necesario solo mientras el Blueprint no esté vinculado; si se vincula (checklist
de la cabecera de `render.yaml`), el bloque `tenderflow-alertmanager` crea el
servicio y estos pasos se reducen a poner los secretos.

```
[ ] 1. Render → New → Private Service → Build from a Dockerfile, sobre este
       repositorio.
       - Dockerfile path: docker/Dockerfile.alertmanager
       - Docker build context: . (la raíz; el Dockerfile copia
         observability/alertmanager.yml)
       - Name: tenderflow-alertmanager   ← el nombre EXACTO que enruta
         observability/prometheus.render.yml
       - Region: frankfurt               ← la misma que tenderflow-prometheus,
         o la red privada no los une
       - Instance type: starter
[ ] 2. Disk: name `alertmanager-data`, mount path `/alertmanager`, 1 GB. Sin
       disco, cada redeploy reenvía todo lo que siga activo y borra los
       silencios puestos durante un incidente.
[ ] 3. Environment: crear estas variables (las cuatro primeras son las MISMAS
       que ya usa observability/alerts.py; no hay un segundo juego de
       credenciales SMTP).

       | Variable | Valor | ¿Obligatoria? |
       |---|---|---|
       | `PORT` | `9093` | sí — ver nota de abajo |
       | `ALERT_EMAIL_TO` | destinatario de alertas | sí |
       | `ALERT_SMTP_USER` | cuenta remitente | sí |
       | `ALERT_SMTP_PASSWORD` | App Password de 16 caracteres | sí |
       | `ALERT_SMTP_HOST` | `smtp.gmail.com` | no (default) |
       | `ALERT_SMTP_PORT` | `587` | no (default) |
       | `ALERTMANAGER_WEBHOOK_URL` | URL del dead-man's-switch | no, pero §3 |

       `PORT` es obligatoria porque el entrypoint arranca con
       `--web.listen-address=0.0.0.0:${PORT:-9093}` y Render inyecta su propio
       `PORT` (10000) si el servicio no lo trae: el Alertmanager escucharía en
       10000 y Prometheus enrutaría a 9093, donde no hay nadie. El fallo sería
       silencioso — exactamente lo que este servicio existe para terminar.
[ ] 4. Desplegar y leer los logs del arranque. Si faltan credenciales SMTP, el
       entrypoint lo grita: «ALERTMANAGER: faltan
       ALERT_EMAIL_TO/ALERT_SMTP_USER/ALERT_SMTP_PASSWORD».
[ ] 5. Redesplegar `tenderflow-prometheus` para que tome el bloque `alerting:`
       de observability/prometheus.render.yml (la config va horneada en la
       imagen, así que hace falta un build nuevo).
[ ] 6. Comprobar el `Watchdog` con los tres pasos de §3.
[ ] 7. Provocar un aviso real de prueba y confirmar que el correo llega:
       silenciar nada, esperar a la primera `warning` legítima, o —si hace
       falta forzarlo— bajar temporalmente el umbral de una regla en una rama y
       revertirlo. No hay endpoint de «enviar alerta de prueba».
[ ] 8. Anotar aquí la fecha en que el plano B quedó verificado en producción, y
       cambiar el «Estado a 2026-09-06» de §1.
```

---

## 6. Qué mirar según lo que recibas

| Lo que pasa | Plano | Dónde mirar primero |
|---|---|---|
| Llega un email `[TenderFlow] [ERROR] …` | A | La tabla de §7, por título de alerta |
| Llega un email `[TenderFlow] [CRITICAL] <alertname>` | B | `observability/alert_rules.yml`, la regla por `alertname`; la anotación `description` dice por dónde empezar |
| **Deja de llegar el `Watchdog`** | B | El canal entero está caído: Prometheus, Alertmanager o SMTP. Nada de este fichero es fiable hasta arreglarlo (§3) |
| No llega nada y sospechás igual | ambos | `alert_delivery_failed_total` (§4) y la tabla `ops_events` en la BD |

---

## 7. Alertas del plano A y su diagnóstico

| Alerta | Nivel | Fuente | Umbral |
|---|---|---|---|
| Feed diario con lag | WARN | `check_daily_lag()` | > 8h sin actualización |
| Feed diario: fallos consecutivos | ERROR | `check_daily_consecutive_failures()` | 3 fallos seguidos |
| Modelo ML SAP obsoleto | WARN | `check_ml_model_staleness()` | > 30 días desde entrenamiento |
| Scheduler job timeout | ERROR | `scheduler/loop.py` | > 600s (configurable) |
| Scheduler job failure | ERROR | `scheduler/loop.py` | Excepción en ejecución |
| DB pool acquire timeout | ERROR | `db/connection.py` | > 10s sin conexión |

### 7.1 Feed diario con lag (> 8h)

**Síntoma**: alerta «Feed diario con lag de Xh».

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
        print(f'Lag: {(datetime.now(UTC) - dt).total_seconds() / 3600:.1f}h')
    except Exception:
        pass
else:
    print('No cursor found — el scraper nunca corrió')
"
```

**Causas comunes**: el workflow `scrape-daily.yml` falló; el feed ATOM de PLACSP
no tiene datos nuevos (normal fuera de horario laboral); timeout de red al
descargar los ZIP.

**Acción**:

```bash
python -m scheduler.run_update

python -c "
from db.database import connect
with connect() as c:
    for r in c.execute(
        'SELECT fuente, status, created_at FROM extraction_runs '
        'ORDER BY created_at DESC LIMIT 5'
    ).fetchall():
        print(f'  {r[0]:20s} {r[1]:10s} {r[2]}')
"
```

### 7.2 Feed diario: 3 fallos consecutivos

```bash
python -c "
from services.extraction_runs import load_recent_daily_statuses
print(f'Últimos 5 estados: {load_recent_daily_statuses(5)}')
"
```

**Causas comunes**: PLACSP cambió la estructura del ATOM; error de parseo XML
(ver DLQ); timeout de red persistente.

```bash
# Errores en la DLQ
python -c "
from db.database import connect
with connect() as c:
    for r in c.execute(
        \"SELECT error_type, COUNT(*) AS n, payload_ref FROM dlq \"
        \"WHERE scope='parse' GROUP BY error_type, payload_ref ORDER BY n DESC LIMIT 10\"
    ).fetchall():
        print(f'  {r[0]:20s} n={r[1]:4d}  ref={r[2]}')
"

python -m scheduler.dlq_retry
```

### 7.3 Modelo ML SAP obsoleto (> 30 días)

```bash
python -c "
import joblib
from pathlib import Path
p = Path('models/sap_classifier.pkl')
print(joblib.load(p).metadata.get('trained_at', 'unknown') if p.exists() else 'Modelo no encontrado')
"

python -m scraper.ml_training --force
```

### 7.4 Scheduler job timeout

**Causas comunes**: job pesado (`daily_atom`, `recent_bulk`) por encima de 600 s;
proceso esperando un lock de BD; presión de memoria.

```bash
# Subir el presupuesto, o bajar el trabajo
export SCHEDULER_JOB_TIMEOUT_SECONDS=1200
export SCHEDULER_BULK_MONTHS=1
```

### 7.5 Scheduler job failure

```bash
docker compose logs scheduler --tail=50
docker compose logs scheduler 2>&1 | grep -i "error\|exception\|failed"

python -c "from scheduler.jobs import build_default_registry; \
    [j.fn() for j in build_default_registry() if j.name == 'NOMBRE_JOB']"
```

### 7.6 DB pool acquire timeout

**Síntoma**: `db_pool_acquire_timeout` en los logs, o la alerta
`PgPoolAcquireTimeoutHigh` del plano B.

Este apartado describía `PRAGMA journal_mode` y checkpoints del WAL: era el
diagnóstico de SQLite, motor que se retiró en ADR-021. El equivalente en
Postgres es mirar quién retiene las conexiones:

```bash
# Conexiones abiertas y qué están haciendo
psql "$DATABASE_URL" -c "
SELECT state, count(*), max(now() - state_change) AS mas_antigua
FROM pg_stat_activity WHERE datname = current_database()
GROUP BY state ORDER BY count(*) DESC;"

# Consultas vivas de más de un minuto: candidatas a ser la causa
psql "$DATABASE_URL" -c "
SELECT pid, now() - query_start AS duracion, left(query, 80)
FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '1 minute'
ORDER BY duracion DESC;"
```

**Acción, por orden de coste**: (1) comprobar que el techo de conexiones de la
API cabe en el `Pool Size` del pooler de Supabase — el cálculo está comentado en
`render.yaml`, junto a `DB_POOL_SIZE`/`DB_READ_POOL_SIZE`, y el incidente del
2026-08-24 fue exactamente ese desajuste; (2) mover jobs de escritura fuera de la
ventana de ingesta; (3) el resto de mitigaciones, en
`docs/runbooks/persistence-tripwires.md`.

---

## Notas generales

- El plano A envía por email solo si `ALERT_EMAIL_TO` y `ALERT_SMTP_*` están
  configurados; sin SMTP, las alertas se quedan en los logs estructurados y
  suman `alert_delivery_failed_total{motivo="not_configured"}`.
- `ALERT_MIN_LEVEL` (default `warn`) filtra el plano A. **No filtra el plano B**:
  el umbral de una regla de Prometheus vive en su `expr`.
- Para suprimir una alerta del plano A, ajustar el umbral en
  `observability/alerts.py` o su variable de entorno; para una del plano B, su
  regla en `observability/alert_rules.yml` (o un silencio temporal en el
  Alertmanager, que el disco conserva entre redeploys).
