# Runbook: Disaster Recovery (Postgres / Supabase)

**Propósito**: recuperar el servicio tras un fallo catastrófico: pérdida o
corrupción de la base de datos, proyecto de Supabase inaccesible, despliegue
roto en Render, plano de cron parado o credenciales comprometidas.

**Responsable**: quien esté de guardia (ver
[observability-alerts.md](observability-alerts.md) §receptor de guardia).

| Objetivo | Valor declarado | Estado |
|---|---|---|
| RTO (tiempo de recuperación) | < 2 h | **afirmado, no ensayado de extremo a extremo** — ver §8 |
| RPO (pérdida máxima de datos) | < 24 h (backup diario gestionado por Supabase; menor con PITR si el plan lo incluye) | depende del plan de Supabase, no de este repo |

**Reescrito el 2026-09-14.** La versión anterior de este runbook abría
`data/licitaciones.db` con `sqlite3`, motor retirado en
[ADR-021](../adr/ADR-021-retirada-sqlite.md): quien lo hubiera seguido en un
incidente habría perdido la primera media hora comprobando un fichero que no
existe. Todo lo que sigue es Postgres.

---

## 0. Antes de tocar nada: cuál es el fallo

Los síntomas se parecen y las acciones no. Diagnosticar primero, en este orden:

```bash
# 1. ¿Responde la API y con qué schema?
curl -s https://<api>/api/v1/health/ready | python -m json.tool
#    - "schema": "ok"        → código y base alineados
#    - "schema": "behind"    → falta migrar (no es un desastre: §5)
#    - "schema": "ahead"     → el código desplegado es más viejo que la base (rollback de deploy, §4)
#    - sin respuesta         → servicio caído (§4) o base inaccesible (§2)

# 2. ¿Responde la base?
psql "$DATABASE_ADMIN_URL" -c "SELECT now(), current_database(), version();"
psql "$DATABASE_ADMIN_URL" -c "SELECT COUNT(*) FROM licitaciones;"
psql "$DATABASE_ADMIN_URL" -c "SELECT MAX(fecha_extraccion) FROM licitaciones;"

# 3. ¿Cuál es el último backup bueno?
#    Dashboard de Supabase → Database → Backups (diarios, y PITR si está activo).
```

| Síntoma | Escenario | Sección |
|---|---|---|
| `SELECT` falla, filas corruptas, tablas desaparecidas | Pérdida o corrupción de datos | §2 |
| Proyecto de Supabase pausado, borrado o inaccesible | Pérdida del proveedor | §3 |
| API caída o devolviendo 5xx tras un push | Despliegue roto | §4 |
| `schema: behind` | Migraciones sin aplicar | §5 |
| Datos frescos no llegan desde hace > 36 h | Plano de cron parado | §6 |
| Credencial expuesta | Compromiso | [SECURITY.md](../SECURITY.md) tabla de rotación, y después §7 |

---

## 1. Requisitos del que actúa

- `DATABASE_ADMIN_URL` (rol dueño; **solo** para restaurar y migrar).
- Acceso a GitHub (secrets y `gh`), al dashboard de Render y al de Supabase
  (con permiso para restaurar backups del proyecto).
- `psql` en la máquina.

---

## 2. Restaurar la base de datos desde backup

Las copias las hace Supabase (backups diarios del proyecto y, según el plan,
Point-in-Time Recovery). El repo ya no mantiene dumps propios: `backup.yml`,
`restore-drill.yml` y `scripts/backup_db.py` se retiraron el 2026-09-28 por
duplicar lo que el proveedor ya hace. Aquí solo el orden y las comprobaciones
que un incidente exige.

```bash
# 2.1 Congelar la escritura: apagar el cron y el worker mientras dure la restauración.
#     Actions: gh workflow disable scrape-daily.yml  (y ml-scoring, pliegos, healthcheck)
#     Render:  suspender tenderflow-worker desde el dashboard (o SCHEDULER_PLANE vacío si el cron corre ahí, ADR-033)

# 2.2 Elegir el punto de restauración: Supabase → Database → Backups.
#     Con PITR, el instante justo anterior al incidente; si no, el último diario.

# 2.3 Restaurar desde el dashboard (mismo proyecto, misma URL). El proyecto
#     queda inaccesible mientras dura; esperar a que vuelva a "Healthy".

# 2.4 Comprobar.
DATABASE_URL="$DATABASE_ADMIN_URL" ENV=prod APP_PROFILE=scraper python -m alembic current
#   → debe ser la cabeza del repo (si no: §5)
psql "$DATABASE_ADMIN_URL" -c "SELECT COUNT(*) FROM licitaciones;"
psql "$DATABASE_ADMIN_URL" -c "SELECT source, last_seen_updated FROM ingestion_cursors ORDER BY 1;"
python scripts/verify_audit_chain.py             # la cadena de auditoría sigue íntegra
```

**Los cursores de ingesta vuelven al punto del backup.** No hay que
recalcularlos: cada conector retoma desde su cursor y el upsert es idempotente
(AGENTS.md §3.2), así que la siguiente pasada de `scrape-daily` rellena el
hueco sola. Lo que sí se pierde es lo que los usuarios escribieron después del
backup (oportunidades, comentarios, seguimientos): avisarlo en el
post-mortem con la hora exacta del punto restaurado.

```bash
# 2.5 Reactivar y forzar una pasada.
gh workflow enable scrape-daily.yml && gh workflow run scrape-daily.yml
# Si el hueco supera lo que cubre el ATOM en vivo, bulk del mes en curso:
gh workflow run scrape-bulk.yml -f months=1
```

---

## 3. Pérdida del proveedor: reconstruir el proyecto de Supabase

Solo si el proyecto no vuelve (borrado, región caída sin ETA, cuenta bloqueada).

1. Crear proyecto nuevo en Supabase **en la región de la UE que documente
   [docs/legal/subencargados.md](../legal/subencargados.md)**; anotar la nueva
   `DATABASE_URL` con `sslmode=verify-full` y el certificado en `db/certs/`.
2. Extensiones antes de restaurar:
   `CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS unaccent;`
3. Recuperar los datos. Los backups de Supabase viven dentro del proyecto: si
   el proyecto se pierde, pedir a soporte de Supabase la última copia y
   restaurarla con `psql`/`pg_restore` contra la URL nueva (rol dueño). Si no
   hay copia recuperable, crear el esquema con
   `DATABASE_URL="$DATABASE_ADMIN_URL" python -m alembic upgrade head` y
   reingerir los datos públicos con `gh workflow run scrape-bulk.yml`; los
   datos de usuario (oportunidades, comentarios, seguimientos) se pierden.
4. Ejecutar `scripts/setup_pg_roles.sql` para recrear `tenderflow_app` y las
   políticas RLS; verificar que puede DML y no DDL
   ([migracion-persistencia.md](../archive/runbooks/migracion-persistencia.md) paso 9).
5. Rotar secretos: `DATABASE_URL` y `DATABASE_ADMIN_URL` en GitHub Secrets y en <!-- pragma: allowlist secret -->
   los cinco servicios de Render (`render.yaml` los declara `sync: false`).
6. Redesplegar la API (`gh workflow run deploy.yml`) y esperar
   `/health/ready → schema: ok`.
7. Reactivar el cron (§2.5).

---

## 4. Despliegue roto en Render

Un push a `master` que deja la API en 5xx o sin arrancar.

```bash
# 4.1 Rollback del servicio: dashboard de Render → tenderflow-api → Deploys → "Rollback".
#     (Con el Blueprint vinculado y autoDeploy apagado, deploy.yml es el único disparador.)

# 4.2 Si el push llevaba migración y el código antiguo no la entiende (`schema: ahead`):
DATABASE_URL="$DATABASE_ADMIN_URL" ENV=prod APP_PROFILE=scraper python -m alembic downgrade -1
#     Las revisiones son append-only y todas tienen downgrade (AGENTS.md §3.3);
#     `plan` primero: alembic history -r current:head para ver qué se deshace.

# 4.3 Comprobar y anotar.
curl -s https://<api>/api/v1/health/ready | python -m json.tool
```

Nunca `--no-verify`, nunca `git push --force` a `master` para "arreglar" un
deploy: el camino es rollback + fix + PR.

---

## 5. Migraciones pendientes (`schema: behind`)

No es un desastre, pero aparece en todos los demás. `migrate.yml` es manual a
propósito: producción no migra sola.

```bash
# plan antes de apply: qué revisiones faltan
DATABASE_URL="$DATABASE_ADMIN_URL" ENV=prod APP_PROFILE=scraper python -m alembic history -r current:head
# ventana: comprobar en Supabase → Database → Backups que hay copia reciente, y después
gh workflow run migrate.yml
# verificar
curl -s https://<api>/api/v1/health/ready | grep -o '"schema": *"[a-z]*"'
```

Si faltan muchas revisiones (producción llegó a ir 30 por detrás en
septiembre de 2026), aplicarlas **por tandas** y comprobar `/health/ready` y
`make audit-truth-check` entre tanda y tanda.

---

## 6. Plano de cron parado

Los datos dejan de refrescarse pero todo lo demás responde.

- **Actions** (`SCHEDULER_PLANE=actions`): GitHub desactiva los `schedule:` tras
  60 días sin actividad en el repositorio y no avisa. `gh workflow list` muestra
  `disabled_inactivity`; `gh workflow enable <fichero>` los reactiva. También
  mirar la pestaña Usage por si se agotaron los minutos.
- **Worker** (`SCHEDULER_PLANE=worker`, [ADR-033](../adr/ADR-033-plano-de-cron-en-el-worker.md)):
  `/health/ready` del worker expone `cron_plane` y el último tick; si no
  avanza, reiniciar el servicio `tenderflow-worker` desde Render y revisar
  `ops_events`.
- En ambos casos, `scheduler/healthcheck.py` (cada 6 h) debería haber
  alertado por `source_ingestion_health`; si no lo hizo, el receptor de
  alertas es el segundo incidente (ver [observability-alerts.md](observability-alerts.md)).

---

## 7. Después de una rotación de credenciales

Tras seguir la tabla de rotación de [SECURITY.md](../SECURITY.md):

1. Revocar todas las sesiones y claves si la credencial comprometida fue
   `API_HMAC_SECRET`, `SIGNING_KEY` o `TOTP_ENCRYPTION_KEY` (los usuarios
   vuelven a entrar; las claves API se reemiten desde `/ajustes`).
2. Redesplegar los cinco servicios de Render y relanzar los workflows que la
   usen.
3. Verificar `python scripts/verify_audit_chain.py` y que `/security/audit/verify`
   sigue devolviendo íntegro: la cadena registra la rotación.

---

## 8. Ensayo (game day)

El RTO de la cabecera es una afirmación hasta que esta tabla tenga una fila:
nada prueba §2 entero con cron apagado, cursores retomando y usuarios avisados.

Cómo ensayar sin tocar producción: restaurar un backup de Supabase en un
proyecto nuevo ("Restore to new project" en el dashboard), apuntar un
despliegue de preview a esa base, lanzar una pasada de `scrape-daily` a mano y
cronometrar de principio a fin.

| Fecha | Escenario ensayado | Duración medida | Resultado | Quién |
|---|---|---|---|---|
| _(sin ensayos registrados)_ | | | | |

---

## 9. Post-mortem

En `docs/runbooks/incident-playbooks.md` o el canal de incidentes, dentro de
las 48 h: causa raíz, cronología con horas, tiempo de recuperación medido,
datos perdidos (hora del punto restaurado y qué escribieron los usuarios después), y qué
cambia en este runbook. Un runbook que no cambia tras un incidente es un
runbook que nadie leyó.
