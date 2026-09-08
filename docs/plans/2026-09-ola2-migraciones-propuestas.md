---
tags: [plan, arquitectura, migraciones, propuesta]
---

# Ola 2 — diseño y migraciones propuestas, sin escribir

Compañero de [2026-09-plan-arquitectura-v2.md](2026-09-plan-arquitectura-v2.md) §6.
Cubre **T1, T2, T3, T4 y T6**: los cinco ítems de la Ola 2 que llevan gate
**[§6]** de migración. **T5 y T7 no están aquí** porque no tocan schema y se
implementan en la misma tanda que este documento.

**Estado: PROPUESTO el 2026-09-08. Ninguna de estas revisiones existe.** No hay
ningún fichero nuevo en `db/alembic/versions/`; la cabeza del repo sigue en
`v112`. Este documento es lo que hay que leer antes de escribirlas.

## Por qué no se escribieron

Dos razones, ambas del propio plan:

1. **D20 no las pre-autoriza.** La fila D20 de la §3 del plan enumera lo que
   queda pre-autorizado para este plan: «Migraciones `v103+` de **S2, S3, S4 y
   S5**». La Ola 2 no está en esa lista, y la propia fila cierra con «Lo que no
   enumera sigue pidiendo OK puntual». AGENTS.md §6 dice lo mismo: tocar
   `db/alembic/` requiere OK explícito.
2. **Producción va once revisiones por detrás.** Según el §8 del plan de
   septiembre, producción estaba en `v97`; el repo va por `v112`. Apilar cinco
   revisiones más —dos de ellas recreando claves primarias de tablas vivas—
   sobre once sin aplicar convierte el primer despliegue en un salto de
   dieciséis. La acción humana pendiente (aplicar `v98`–`v112`) es prerrequisito
   de todo lo que sigue, no un detalle de operación.

El mantenedor decidió el **2026-09-08** ejecutar solo lo que no toca schema y
dejar esto escrito. Cuando dé el OK, cada ítem se abre en su propia rama con
`alembic upgrade --sql` (**plan antes de apply**) contra una copia, en el orden
de la §9 del plan: **T1 → T4 → T2 → T3**, y T6 al final porque depende de T4.

## Regla común a las cinco

Ninguna de estas migraciones puede ser destructiva en su primera revisión.
El patrón del repo, y el que aquí se asume, es el de `v68`/`v69`: **añadir la
columna en una revisión, indexar `CONCURRENTLY` en otra**, escribir en las dos
durante una ventana de lectura dual, y solo entonces retirar la vieja en una
tercera. Ese par de revisiones (`v68_fecha_pub_date_generated.py` y
`v69_fecha_pub_d_index_concurrent.py`) es el precedente literal de T2 y debe
copiarse, no reinventarse.

---

## T1 — Seguimiento unificado

**Hoy: no existe nada.** Cero coincidencias de `follows` fuera del plan.

### Lo que hay que sustituir (medido el 2026-09-08)

| Primitiva | Tabla | Rutas | Endpoints |
|---|---|---|---|
| Favoritos | `watchlist_items` (`v45`) | `api/routes/watchlist_items.py:63,79,97` | 3 |
| Empresas vigiladas | `watchlist_empresas` (`v36`) | `api/routes/competitive.py:485,493,521` | 3 |
| Reglas | `watchlist_rules` (`v43`) | `api/routes/watchlist_rules.py:166,177,205,228,239,282,310` | 7 |
| Descartes del Radar | `radar_dismissals` (`v76`, `v103`) | `api/routes/radar.py:169,176,212` | 3 |
| Vistas guardadas | `saved_filters` | `api/routes/saved_filters.py:71,82,109` | 3 |
| Perfil de scoring | `user_profiles` | `api/routes/me.py:425,453,499` | 3 |

**6 tablas / 22 endpoints** — la cifra de la métrica §7 del plan cuadra exacta.

**Tres piezas que la métrica no cuenta y que hay que decidir si entran**, porque
si no entran la unificación no unifica:

- **`watchlist_cpv`** — séptima tabla de seguimiento, legado. Su migración a
  reglas ya la hace el frontend en
  `web/src/app/(dashboard)/mi-watchlist/_hooks/use-legacy-rule-migration.ts`.
- **`cuentas_objetivo`** — «seguir un órgano» **ya existe**, con 3 endpoints
  (`api/routes/cuentas.py:84,95,124`) y servicio propio (`services/cuentas.py`,
  `seguir_organo` / `dejar_de_seguir`). Es literalmente `target_type = organo`
  escrito antes de tiempo, y es el modelo más cercano a `follows` que hay hoy:
  **la forma de `follows` debe salir de aquí**, no inventarse de cero.
- **`api/routes/watchlist_feed.py:31`** — un endpoint más, de lectura.

### Migración propuesta (una sola revisión, aditiva)

```sql
CREATE TABLE follows (
    id               bigserial PRIMARY KEY,
    organization_id  bigint      NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id          bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type      text        NOT NULL,
    target_id        text        NOT NULL,
    kind             text        NOT NULL,
    visibility       text        NOT NULL DEFAULT 'private',
    channels_json    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_follows_target_type
        CHECK (target_type IN ('licitacion','lote','empresa','organo','cpv')),
    CONSTRAINT ck_follows_kind
        CHECK (kind IN ('seguir','descartar'))
);
CREATE UNIQUE INDEX uq_follows_identidad
    ON follows (organization_id, user_id, target_type, target_id, kind);
CREATE INDEX ix_follows_org_target ON follows (organization_id, target_type, target_id);
```

`user_id` y no `user_key`: **T1 va antes que T4 en la §9 precisamente para no
nacer con la deuda que T4 viene a pagar.** Eso obliga a que el backfill traduzca
`user_key → user_id` por email al copiar, que es el mismo trabajo que T4 hará
después para las nueve tablas restantes.

**Riesgo**: bajo en la migración (tabla nueva), **alto en la retirada**. La
retirada de los nueve endpoints antiguos es un cambio breaking del contrato
público y exige RFC con fecha, igual que hizo D19 con los de analítica
(`docs/rfc/2026-09-06-rfc-retirada-endpoints-analitica.md` es la plantilla).

**Lo que no puede faltar antes de retirar nada**: el script de paridad que
reproduce, para cada usuario, favoritos + empresas + descartes desde `follows`
con **cero diferencias**, ejecutado **en producción**. Sin esa ejecución, la
lectura antigua no se toca. `scripts/check_openapi_contract.py` ya sirve de gate
para el contrato.

**Frontend**: hoy hay tres hooks distintos para la misma acción —
`web/src/hooks/use-watchlist-items.ts`,
`web/src/app/(dashboard)/detalle/_hooks/use-detalle-favoritos.ts` y
`web/src/app/(dashboard)/radar/_hooks/use-radar-consola.ts`. El criterio del
plan («un solo control "Seguir" con el mismo componente») se mide contra esos
tres.

---

## T2 — Núcleo tipado

**Hoy: las tres columnas no existen.** El estado real de `licitaciones`
(`docs/database-schema.md:163-204`) es `importe double precision`,
`fecha_publicacion text`, `fecha_limite text`, y `fecha_inicio`, `fecha_fin`,
`fecha_actualizacion_fuente`, `fecha_extraccion`, `primera_extraccion` **todas
`text`**.

### Migración propuesta (dos revisiones, patrón `v68`/`v69`)

```sql
-- revisión A: columnas sombra, sin índices
ALTER TABLE licitaciones
    ADD COLUMN fecha_publicacion_ts timestamptz,
    ADD COLUMN fecha_limite_ts      timestamptz,
    ADD COLUMN importe_num          numeric(14,2);

-- revisión B, aparte y fuera de transacción
CREATE INDEX CONCURRENTLY ix_lic_fecha_publicacion_ts ON licitaciones (fecha_publicacion_ts);
CREATE INDEX CONCURRENTLY ix_lic_fecha_limite_ts      ON licitaciones (fecha_limite_ts);
```

El backfill va **batcheado y con ventana de lock declarada**, no en una
transacción. Es la misma lección que dejó el bug de
`limpiar_ml_proba_fuera_de_poblacion` en el PR #274: un `UPDATE` sin `LIMIT`
sobre esta tabla toca centenares de miles de filas mientras el scraper escribe.

### Las tres trampas de este ítem

1. **`periodo_publicacion_sql()`** (`db/sql_fragments.py:407-455`) es
   **componente de la clave canónica** (`clave_canonica_sql:545`). Cambiarla
   mueve la clave, y con ella el sitemap y las vistas materializadas `v101` y
   `v102`. La lectura dual tiene que dejar la clave **byte a byte idéntica**
   durante toda la ventana; hay un test que lo puede fijar antes de empezar.
2. **`iso_guard(column)`** (`db/sql_fragments.py:318-334`, con `ISO_MIN='1900'`
   / `ISO_MAX='3000'` en `:293-294`) es un rango **lexicográfico sobre texto**,
   escrito así a propósito para poder usar el btree. Con `timestamptz` el
   fragmento no se adapta: **desaparece**. Hay que comprobar quién lo llama
   antes de retirarlo.
3. **`FECHA_FIN_SQL`** (`:155-168`) y `FECHA_FIN_ORIGEN_SQL` (`:185`) castean
   con `substr(...,1,10)::date` y `CAST(l.duracion_valor AS INTEGER)`. Son los
   que el criterio de `EXPLAIN` sin cast en tiempo de ejecución vigila.

### `shared/numeric.values_equal` — y una discrepancia que hay que resolver antes

`shared/numeric.py:53-65` compara con `math.isclose(rel_tol=1e-5, abs_tol=1e-9)`
solo para números. Existe porque el round-trip float fabrica diffs falsos.
Consumidores de producción, exactamente tres:

- `db/upsert.py:797` — detección de `changed_fields` para `licitaciones_history`
- `services/contract_events.py:151,214`
- `services/avisos.py:172`

**Discrepancia a resolver antes de tocar nada**: el docstring de
`shared/numeric.py:1-11` afirma que `licitaciones.importe` es `real`/float4,
pero `docs/database-schema.md:169` lo declara `double precision`. Uno de los dos
miente, y de cuál sea depende si la tolerancia de `1e-5` es necesaria o es
folclore. **Se comprueba contra la BD real**, no leyendo más código.

El criterio del plan («`values_equal` deja de necesitarse para `importe`: un
test de round-trip exacto pasa **contra Postgres**») no se puede verificar en
esta máquina: no hay Postgres. `tests/test_shared_numeric.py:29` prueba el
round-trip **en memoria**, que no es lo mismo.

### Un trozo de T2 que no necesita migración y sí se puede hacer ya

`scripts/audit_domain_truth.py` mide cinco cosas (docstring `:1-16`, umbrales en
`:60-84`) y **ninguna es «fechas no ISO»**: cero coincidencias de `ISO` en el
fichero. Esa categoría ya estaba prometida en el plan anterior
([2026-09-plan-arquitectura.md](2026-09-plan-arquitectura.md) §O0.3) y sigue sin
hacerse. Es el contador que da el criterio de aceptación «cuenta cero fechas no
ISO», así que **sin él T2 no tiene forma de declararse cerrada**. Se puede
escribir hoy, sin schema, y deja el numerador listo para cuando la migración
llegue.

---

## T3 — Tecnología: una sola verdad

**Hoy: la tabla origen existe y ya se lee; lo que falta es cortar a los
productores.** `licitacion_tecnologia_score` es de `v30`
(`docs/database-schema.md:1160-1172`: `licitacion_id, tecnologia, probabilidad,
threshold_aplicado, computed_at`, PK compuesta, índices `idx_lts_lic` e
`idx_lts_tecnologia`) y ya la leen `db/models.py:96`,
`db/repositories/licitaciones.py:298-307,641,1144-1153`,
`db/repositories/aggregates.py:1776-1813` y `api/routes/licitaciones.py:1229`.

### Los cuatro productores que hay que cortar

1. `scraper/ml_training.py:574` `precompute_ml_tecnologias()` → el `UPDATE` de
   `:669` **clobberea las tres columnas en cada pasada**.
2. `db/repositories/tecnologia_pliego.py:400-401` — `UPDATE licitaciones SET
   ml_tecnologias, ml_proba_max, ml_tech_principal`, y en `:406` un `INSERT INTO
   licitacion_tecnologia_score`. **Los dos lados escritos desde el mismo sitio**:
   es aquí donde la duplicidad deja de ser accidente y pasa a ser diseño.
3. `scraper/pipeline.py:232` (`lic.ml_tech_principal = pred["principal"]`) y
   `:320`, que lo pasa al upsert.
4. `db/upsert.py` — `tecnologia`, `ml_tecnologias`, `ml_proba_max` y
   `ml_tech_principal` son campos del dataclass (`:162-167`) y entran en el `ON
   CONFLICT DO UPDATE` **sin `COALESCE`** (no están en
   `_LIC_COALESCE_UPDATE_FIELDS`, `:244`), o sea que **cada reingesta los
   nulea**. Ya levantado como P2 en `docs/IMPROVEMENT_BACKLOG.md:385-393`.

### `tech_signal_merge` es el parche, no la solución

Es el paso 3 de 15 de `CANONICAL_STEPS` (`scheduler/pipeline_runs.py:43-59`),
marcado **bloqueante** en `STEP_TIER:88`, implementado en `_run_tech_signal_merge`
(`:322-353`) sobre `services/tech_signal.py::merge_doc_signals` (`:115-167`) y
persistido en `db/repositories/tecnologia_pliego.py` (lock
`tenderflow.tech_signal_merge` en `:66-68`). Corre **cada cuatro horas**.

Los propios comentarios del repo dicen para qué está:
`scheduler/pipeline_runs.py:17` y `db/repositories/tecnologia_pliego.py:10,197`
lo describen como reparación del clobber de `precompute_ml_tecnologias`.
**Es un paso bloqueante del pipeline cuya única función es deshacer el daño de
otro paso del mismo pipeline.** El criterio del plan («cero reparaciones en
siete días de cierre, medido en `ops_events`, y después se retira de
`CANONICAL_STEPS`») es la forma correcta de matarlo: primero se demuestra que ya
no repara nada, después se quita.

Al retirarlo, `scripts/check_job_parity.py:171-217` fallará por el job huérfano:
va en el mismo commit.

### El guardrail que hay que ampliar

`tests/test_dedup_guardrail.py` escanea `_LITERALES_PROHIBIDOS` (`:343-354`) y
hoy tiene **exactamente dos categorías**: `universo` y `duplicados`. Ratchet
`_COPIAS_LITERALES_MAX = 0` (`:390`). T3 pide una tercera:

```python
"tecnologia": r"UPDATE\s+licitaciones\s+SET\s+[^;]*\b(tecnologia|ml_tecnologias|ml_tech_principal)\b",
```

Exenta `db/sql_fragments.py` y `db/alembic/versions/` como ya hace (`:336-339`).
**Esa categoría es lo que impide que T3 se deshaga sola tres meses después**, y
—al contrario que el resto del ítem— se puede escribir sin migración, en cuanto
los productores estén cortados.

**Migración**: vista o trigger que derive las tres columnas, más reconstrucción
de la vista materializada según ADR-026 §A. **Riesgo alto**: toca la ingesta y
la MV a la vez.

---

## T4 — `user_key` → `user_id`, fase 2

**Fase 1 hecha, fase 2 sin empezar.** `scripts/check_user_key_ratchet.py` existe
y funciona; `CONGELADOS` (`:119-186`) lista **64 ficheros** de producción y
`docs/STATUS.md:68-72` lo confirma.

> **Corrección de la métrica del plan.** La tabla §7 dice «Ficheros con
> `user_key`: 60». El valor real es **64**, y el ratchet lo dice desde que se
> escribió: subió por tres tandas de excepciones anotadas en
> `check_user_key_ratchet.py:75-118`. El plan manda no corregir cifras a mano
> sino volver a medirlas — esta es la medición, del 2026-09-08.

### Las nueve tablas que faltan

De las **doce** tablas con `user_key` (`docs/database-schema.md` líneas 744,
905, 918, 934, 952, 968, 986, 1006, 1028, 1046, 1062, 1456), **tres ya tienen
`user_id`** nullable: `watchlist_cpv` (`:1014`), `watchlist_items` (`:1047`) y
`watchlist_rules` (`:1063`).

Faltan nueve: `audit_log`, `notification_reads`, `pending_digests`,
`radar_dismissals`, `saved_filters`, `user_notifications`, `user_profiles`,
`watchlist_empresas`, `user_event_prefs`.

### Por qué esto no es un `ADD COLUMN` y ya

**`radar_dismissals` tiene `PRIMARY KEY (user_key, id_externo)`**
(`docs/database-schema.md:943`) y **`user_profiles` lo mismo** (`:997`). En esas
dos, `user_key` no es una columna más: es la identidad de la fila. Retirarla
exige recrear la PK, lo que en Postgres significa índice único nuevo
`CONCURRENTLY`, `ALTER TABLE ... ADD CONSTRAINT ... USING INDEX`, y una ventana
en la que las dos claves conviven. **Son las dos migraciones caras de todo el
plan** y las que justifican por sí solas el `--sql` antes del `apply`.

### El breaking que hay que anunciar

`shared/events.py:97-101` publica `user_key` **como campo del payload del
webhook `watchlist_rule.matched`**. Retirarlo rompe a cualquier consumidor
existente: exige RFC con fecha, igual que D19. **Este detalle no está en el
criterio de aceptación del plan y debería estarlo.**

### Lo barato

Los dos puntos de traducción ya están centralizados y son lo primero que se
borra: `scheduler/jobs/event_dispatch.py` (único punto `user_id → user_key` del
despachador, documentado en `check_user_key_ratchet.py:89-96`) y
`services/cuentas.py::_copiar_para_miembro` (`:111-114`).

`shared/identity.user_key_from_email` (`shared/identity.py:28-44`) ya está
marcada `.. deprecated:: 2026-09` con D18 escrito en el docstring.

---

## T6 — Informes programados

**Depende de T4 tanto como de S4 y S5**, y eso el plan no lo dice: las
preferencias de notificación viven en `user_event_prefs(user_key, event_type,
modo)` (`docs/database-schema.md:1451-1461`), **tecleadas por `user_key`**.
Construir el informe encima añade un consumidor más a la deuda que T4 viene a
pagar.

### Lo que ya existe y se reutiliza tal cual

- **`reportlab` está en dependencias**: `pyproject.toml:21`
  (`reportlab>=4,<6`), con overrides de mypy en `:276-277`. **No hace falta
  tocar dependencias**, que es un gate §6 menos.
- **`_build_pdf`** (`api/routes/exports.py:55-117`) ya genera el PDF que sirve
  `GET /exports/download?format=pdf`. Es la base directa del adjunto; el trabajo
  es extraerlo de la ruta, no escribirlo.
- **La baja sin sesión ya está resuelta**: `token_de_baja` /
  `verificar_token_de_baja` / `url_de_baja_alertas`
  (`services/email_digest.py:250,266,281`), firmadas por HMAC y consumidas por
  `GET /watchlist/rules/baja` (`api/routes/watchlist_rules.py:310-329`). El
  criterio «opt-out por usuario» se cumple reutilizando esto.
- **Los cortes del informe ya están calculados**: `services/direccion.py`
  (`corte_con_minimo:109-149` — cuyo docstring en `:123-125` **ya anticipa el
  informe semanal y el PDF como consumidores**; `actividad_de_organizacion:190`),
  vencimientos en `db/repositories/pursuits.py:495-553`, y
  `services/deadline_reminders.py`.

### Lo que falta de verdad

1. **El envío no soporta adjuntos.** `observability/alerts.py:191` construye
   `MIMEMultipart("alternative")` y envía por `smtplib.SMTP` (`:199`): texto y
   HTML, nada más. Hay que pasarlo a `mixed` o añadir un
   `send_email_with_attachment`. **Es el bloqueo técnico real de T6**, y no
   aparece en el ítem del plan.
2. **Las preferencias por organización no existen.** `user_event_prefs` es por
   usuario y por evento; no hay día, hora ni destinatarios.
   `api/routes/organization_settings.py:29,44` es donde vivirían.
   **Aquí está la migración de T6**, y es pequeña comparada con las de T2 y T4.
3. El paso programado: `scheduler/pipeline_runs.py` (`CANONICAL_STEPS`),
   `scheduler/jobs/__init__.py`, `shared/jobs.py` y `scripts/check_job_parity.py`.

### Lo que ya se puede hacer sin migración

Extraer `_build_pdf` de `api/routes/exports.py` a un módulo propio y dar soporte
de adjuntos a `observability/alerts.py`. Las dos cosas son prerrequisito de T6,
ninguna toca schema, y las dos tienen valor por sí solas: el PDF deja de estar
atrapado en una ruta HTTP y las alertas dejan de no poder adjuntar nada.

---

## Resumen para quien dé el OK

| Ítem | Revisiones | Riesgo | Lo que hay que aceptar |
|---|---|---|---|
| T1 | 1 aditiva | Bajo (tabla nueva) / alto en la retirada | RFC de retirada de 9 endpoints + paridad ejecutada **en producción** |
| T2 | 2 (columnas + índices `CONCURRENTLY`) | Alto | La clave canónica no se puede mover: sitemap y MV `v101`/`v102` cuelgan de ella |
| T3 | 1 (vista/trigger) + reconstrucción de MV | Alto | Toca ingesta y MV a la vez; retira un paso bloqueante del pipeline |
| T4 | ~9, dos con recreación de PK | **El más alto** | `radar_dismissals` y `user_profiles` tienen `user_key` en la PK; retirar `user_key` del payload de `watchlist_rule.matched` es breaking y exige RFC |
| T6 | 1 pequeña (preferencias de organización) | Bajo | Depende de T4; y el envío SMTP hoy no admite adjuntos |

**Prerrequisito de las cinco**: aplicar `v98`–`v112` en producción y comprobar
`GET /health/ready` → `schema: ok`.

**Tres trozos se pueden hacer sin esperar al OK**, y cada uno es prerrequisito
de su ítem: la categoría «fechas no ISO» de `scripts/audit_domain_truth.py`
(T2), la tercera categoría del guardrail de literales (T3, en cuanto los
productores estén cortados) y la extracción de `_build_pdf` más los adjuntos
SMTP (T6).
