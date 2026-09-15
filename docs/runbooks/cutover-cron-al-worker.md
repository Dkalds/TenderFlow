---
tags: [runbook, operacion, scheduler]
---

# Runbook — cutover del cron de GitHub Actions al worker

**Qué hace este runbook:** mueve el plano de cron de producción de GitHub
Actions al worker de Render, sin ventana de parada y con vuelta atrás en un
clic. Implementa [ADR-033](../adr/ADR-033-plano-de-cron-en-el-worker.md).

**Quién lo ejecuta:** una persona con acceso al dashboard de Render y permiso
de escritura sobre `.github/workflows/`. **Ningún agente puede hacerlo**: los
pasos 2, 4 y 6 son cambios de configuración en la plataforma y el 7 toca
workflows.

**Estado al escribir esto (2026-09-14):** no ejecutado. El código está en el
árbol y es inerte: `SCHEDULER_PLANE` vale `actions` en producción, así que el
worker arranca el consumidor de la cola y nada más.

---

## 0. Antes de empezar

| Comprobación | Cómo | Qué esperar |
|---|---|---|
| Los dos planos se conocen | `python scripts/check_job_parity.py` | exit 0 |
| Qué jobs se mueven | `python -c "from scheduler.cron_plane import jobs_del_plano; print([j.name for j in jobs_del_plano()])"` | la lista de los `plane="actions"` |
| Qué workflow ejecuta cada uno | `grep -rn "python -m" .github/workflows/*.yml` | un `python -m <module>` por job de la lista |
| El worker está sano | `curl -fsS https://<host-worker>/api/v1/health/ready` | `200` |

Anotá la lista de jobs. Es el contrato del cutover: al terminar, cada uno de
esos nombres tiene que aparecer en los logs del worker con la cadencia
declarada, y en ningún sitio más.

---

## 1. Elegir la ventana

Cualquier día laborable por la mañana, **no** un viernes ni la víspera de un
festivo: la fase de observación dura 48 h y alguien tiene que estar mirando.

Evitar la hora a la que dispara `daily_atom` (el job más largo). Si cae dentro
de la ventana, esperar a que termine antes del paso 2.

---

## 2. Encender el plano en el worker (Render)

Dashboard → `tenderflow-worker` → Environment → añadir:

```
SCHEDULER_PLANE = worker
```

Guardar. Render redespliega el servicio.

> `tenderflow-worker` tiene `autoDeploy: false`, así que el cambio de variable
> **sí** redespliega (Render trata las variables como un deploy) pero un merge a
> `master` no. Es lo que se quiere: el cutover ocurre cuando alguien lo decide.

Verificar en los logs del servicio, en este orden:

```
cron_plane_arrancado   plano=worker  jobs=[...]
cron_plane_planificado intervalos_min={...}
```

Si en su lugar aparece `cron_plane_inactivo`, la variable no llegó al proceso:
revisar que se guardó en `tenderflow-worker` y no en `tenderflow-api`.

**A partir de aquí hay dos planos vivos a propósito.** No pasa nada: los locks
`cron:<job>` de `db.job_locks` deciden cuál de los dos ejecuta cada disparo, y
los jobs que compiten se saltan con `cron_plane_job_saltado_por_lock`. Esta
convivencia es la red de seguridad del cutover, no un accidente.

---

## 3. Observar 48 horas

Lo que hay que ver, una vez por turno:

1. **Cada job de la lista se ejecutó al menos una vez en el worker.** En los
   logs: `scheduler_loop_job_done job=<nombre>`. Los de cadencia diaria tardan
   hasta 24 h en aparecer; los de 4 h, menos de una mañana.
2. **Nadie corrió dos veces el mismo trabajo.** Grafana → panel del scheduler,
   o directamente:
   ```sql
   SELECT name, holder, expires_at FROM job_locks WHERE name LIKE 'cron:%';
   ```
   Un `holder` que empieza por `worker:` es el plano nuevo. Los saltos quedan
   en `cron_plane_job_saltado_por_lock`.
3. **La tasa de error no subió.** `scheduler_job_total{status="error"}` en
   Prometheus, comparado con la misma franja de la semana anterior.
4. **El healthcheck del worker no parpadeó.** Es la señal de que el cron no le
   está comiendo el contenedor. Si hay reinicios, ir al paso 8 (vuelta atrás) y
   reconsiderar el `plan: starter`.

Rellená esta tabla al terminar la observación:

| Job | Primera ejecución en el worker | Duración | ¿Saltado por lock alguna vez? |
|---|---|---|---|
| | | | |

*(Sin datos: el cutover no se ha ejecutado.)*

---

## 4. Congelar Actions sin borrarlo

Todavía **no** se tocan los ficheros. En GitHub: Actions → cada workflow
programado de la lista → `···` → **Disable workflow**.

Es reversible en un clic y deja el histórico intacto. Si algo va mal, se
vuelven a habilitar y el paso 8 no hace falta.

Desde aquí el worker es el único que ejecuta el cron de verdad.

---

## 5. Observar otras 48 horas

Mismas cuatro comprobaciones del paso 3. Ahora, además:

- **Ningún lock debería saltarse.** Un `cron_plane_job_saltado_por_lock` a
  estas alturas significa que hay otro corredor: o quedó un workflow sin
  deshabilitar, o hay dos instancias del worker. Averiguar cuál antes de
  seguir.
- **Ningún job de la lista deja de aparecer.** Un job que no se ve en 48 h es
  un job que el plano no recogió: comprobar su `plane` en el registry.

---

## 6. Retirar `DATABASE_URL` de los secretos de Actions

Este es el paso que compra la mitad del valor del ADR, y el más fácil de
olvidar.

GitHub → Settings → Secrets and variables → Actions. Borrar los secretos que
solo usaba el cron. **Comprobar antes qué otros workflows los leen** —el
`deploy.yml` y los smoke tests tienen los suyos y no se tocan aquí:

```bash
grep -rn "secrets\." .github/workflows/ | grep -i "database\|db_"
```

Si un workflow que no es de cron lo necesita, ese secreto se queda y se anota
aquí por qué.

---

## 7. Borrar los `schedule:` (PR)

Ahora sí, en un PR aparte y con CI verde: quitar el bloque `schedule:` de los
workflows deshabilitados. Dejar el `workflow_dispatch:` — ejecutar un job a
mano sigue siendo útil, y sin él el workflow no se puede lanzar nunca.

Al quitar el `schedule:`, `scripts/check_job_parity.py` **empezará a fallar**
para esos jobs: su regla es que un job `plane="actions"` viva en un workflow
programado. Es correcto que falle, y es la señal de que al mismo PR le toca
cambiar `plane="actions"` por `plane="loop"`… no: el valor correcto no existe
todavía. **Ese es el trabajo de este paso:** añadir a `scheduler/jobs/_base.py`
el plano `worker` en el `Literal`, marcar con él los jobs migrados, y enseñar
al checker a exigir para ese plano lo que corresponde — que el job esté en
`jobs_del_plano()`, y no en un workflow.

Se deja para el final, y no antes, a propósito: mientras exista la posibilidad
de volver atrás (pasos 4 y 8), la declaración del registry tiene que seguir
diciendo la verdad, que es «lo ejecuta Actions».

---

## 8. Vuelta atrás

En cualquier punto anterior al paso 7, y en este orden:

1. Render → `tenderflow-worker` → Environment → `SCHEDULER_PLANE = actions`.
   Guardar. El redespliegue deja el worker como estaba: cola sí, cron no.
   Comprobar en logs: `cron_plane_inactivo`.
2. GitHub → Actions → **Enable workflow** en los que se deshabilitaron.
3. Si se borraron secretos (paso 6), volver a crearlos.

No hace falta tocar la base de datos. Los locks `cron:*` caducan solos por TTL
(`SCHEDULER_JOB_TIMEOUT_SECONDS`, 600 s por defecto). Si alguno quedara
atascado —un worker muerto sin liberar—, `db.job_locks.force_release` lo suelta:

```bash
python -c "from db.job_locks import force_release; force_release('cron:daily_atom')"
```

Después del paso 7 la vuelta atrás ya no es de un clic: hay que revertir el PR.

---

## 9. Qué mirar cuando el cron del worker falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `cron_plane_inactivo` en el arranque | `SCHEDULER_PLANE` no llegó al proceso | Revisar la variable en `tenderflow-worker` |
| Ningún log del cron y el worker vivo | El hilo murió, o `APP_PROFILE` no es `worker` | Reiniciar el servicio; si se repite, es un bug: el bucle traga excepciones por diseño |
| `cron_plane_job_saltado_por_lock` continuo | Otro corredor activo | Buscar el workflow no deshabilitado o la segunda instancia del worker |
| `cron_plane_lock_indisponible` | La tabla `job_locks` no responde | Es un problema de BD, no del cron: [disaster-recovery.md](disaster-recovery.md) |
| `scheduler_loop_job_timeout` repetido | Job más largo que `SCHEDULER_JOB_TIMEOUT_SECONDS` | Subir el timeout **o** partir el job. El hilo colgado no se puede matar (ADR-033 §4): si se acumulan, reiniciar el servicio |
| Reinicios del worker durante un job pesado | OOM: `plan: starter` se quedó corto | Vuelta atrás (paso 8) y subir el plan antes de repetir |
