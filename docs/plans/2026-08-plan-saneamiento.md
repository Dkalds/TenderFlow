---
tags: [plan, saneamiento, multi-agente]
---

# Plan de saneamiento — ejecutable por agentes en paralelo

Aprobado por el usuario el 2026-08-07. Cada stream se ejecuta en su propia
rama/sesión por un agente independiente; este documento es la fuente única de
alcance, criterios de aceptación y orden de merge. Un agente que tome un stream
trabaja **solo** los archivos de ese stream.

## Contexto

La crítica de la app (2026-08-07) encontró una inversión proceso>producto: 68
RFCs y un backlog de 1.009 líneas en un proyecto de 12 días, mientras la página
insignia (Radar) usa un ranking-proxy, `db/analytics.py` está roto del todo,
`pct_pyme` es un KPI hardcodeado a 0.0, hay 3 IDOR latentes allowlisted, 32
excepciones tragadas congeladas (incluida la cadena de auth) y 3 endpoints
devuelven 500 ante un byte malformado. Este plan convierte esa crítica en 7
streams paralelos con archivos disjuntos, orden de merge definido y criterios
de aceptación por stream.

## Decisiones del usuario (2026-08-07, vinculantes)

- **D1 — Poda:** páginas no-core se ocultan de la navegación (sección
  experimental/admin). No se borra código. Lista concreta se aprueba en el PR de S5.
- **D2 — i18n:** español-only. Se retira `web/src/lib/i18n.ts` + `web/public/locales/`.
- **D3 — Gates §6 pre-autorizados SOLO para lo listado aquí:** migración
  Alembic v76 (dismiss del Radar, stream S2), edición de `.github/workflows/ci.yml`
  (`-n auto`, stream S6), cambios de dependencias para Postgres remoto (stream
  S6). Todo otro gate §6 sigue requiriendo OK puntual.
- **D4 — Ejecución:** ramas paralelas por stream, un PR por stream.

## Regla global de congelamiento (vigente durante la Ola 1)

Cero endpoints y cero páginas nuevos fuera de este plan. Excepciones explícitas:
el endpoint de dismiss (S2, cierra un P0 documentado) y, en Ola 2, las páginas
de webhooks/GDPR (backend ya existente).

## Hechos verificados que corrigen el diagnóstico previo

Los agentes ejecutores deben asumir ESTO (verificado en código el 2026-08-07),
no lo que digan docs desactualizados:

1. `GET /analytics/scoring` (`api/routes/analytics.py:186-202`) **ya acepta**
   `limit` (1-500), `ids` CSV y **ya usa sesión** (`get_current_session_user`).
   Lo único que falta para el Radar real: campos en el DTO.
2. `ScoredOpportunity` vive en `services/analytics/scoring.py:66` (NO en
   `shared/dto.py`); `ScoringResult` en `:79`.
3. La migración `v75_users_admin_granted_by` **ya existe** (head actual) pero la
   columna está **inerte**: ni `admin_set_admin` ni `_sync_oauth_admin`
   (`api/routes/auth.py:688`) la escriben/leen. S4 solo cablea código, sin
   migración nueva.
4. La allowlist de operaciones opacas del contrato OpenAPI llegó a **CERO**
   (2026-08-03): las 154 operaciones están tipadas. Nada bloquea derivar hooks
   del esquema generado.
5. La navegación ya NO tiene `PRODUCT_SPACES`: hoy es `SECTIONS`
   (`web/src/lib/navigation.ts:85`) + `web/src/lib/space-views.ts`. El ítem 2 del
   UX_AUDIT está parcialmente obsoleto.
6. Backlog: 30 ítems abiertos; "Cerrados" ocupa las líneas 322-997 (~676 de 1009).
7. Sin `TEST_DATABASE_URL` la suite aborta con `pytest.UsageError`
   (`tests/conftest.py:183-188`). El compose de dev ya tiene servicio `postgres`.

---

## Streams — Ola 1 (paralelos, archivos disjuntos)

| Stream | Rama | Migración | Merge |
|---|---|---|---|
| S0 Meta/proceso | `claude/s0-proceso` | no | 1º (desbloquea congelamiento) |
| S1 Datos | `claude/s1-datos` | no | libre |
| S2 Radar de verdad | `claude/s2-radar` | **v76 (única)** | antes que S4 (comparten `api/app.py`) |
| S3 Frontend fixes | `claude/s3-frontend` | no | libre |
| S4 Seguridad | `claude/s4-seguridad` | no | tras S2 (rebase) |
| S5 Poda navegación | `claude/s5-poda` | no | libre |
| S6 Infra verificación | `claude/s6-infra` | no | libre |

**Conflictos declarados y su regla:**

- `api/app.py`: S2 (registra router de dismiss) y S4 (posible middleware).
  S2 merge primero; S4 rebasa.
- `docs/IMPROVEMENT_BACKLOG.md`: cada stream mueve SOLO sus ítems a Cerrados;
  conflictos triviales se resuelven al rebasar.
- `web/src/lib/navigation.ts` y `space-views.ts`: propiedad EXCLUSIVA de S5.
- `radar/page.tsx` y `use-radar.ts`: propiedad EXCLUSIVA de S2.
- Ningún otro archivo aparece en dos streams.

---

### S0 — Meta/proceso (`claude/s0-proceso`)

**Objetivo:** que el repo deje de escribir sobre sus defectos más de lo que los
arregla, y registrar el congelamiento.

1. **Archivar Cerrados del backlog:** mover `docs/IMPROVEMENT_BACKLOG.md`
   líneas 322-997 a `docs/archive/IMPROVEMENT_BACKLOG_CERRADOS.md` (con enlace
   desde el backlog). El backlog queda en ~330 líneas: convenciones + 30 abiertos
   + plantilla.
2. **Anotar en cada ítem de ratchet del backlog** (excepciones tragadas,
   user_key, KNOWN_5XX, TID251) qué stream/ola de este plan lo vacía, para que
   ningún agente futuro los trabaje en paralelo duplicado.
3. **Registrar el congelamiento en `AGENTS.md` §0:** "Hasta cerrar la Ola 1 de
   `docs/plans/2026-08-plan-saneamiento.md`, no se añaden endpoints ni páginas
   fuera de ese plan". Correr `make check-agent-docs` (valida rutas citadas).
4. **Verificar que este plan está commiteado** como
   `docs/plans/2026-08-plan-saneamiento.md` (lo hace la sesión que lo redactó;
   si su rama no mergeó aún, S0 lo incorpora).

**Verificación:** `make check-agent-docs` verde; enlaces del backlog no rotos.
**Riesgo:** nulo (solo docs).

---

### S1 — Datos (`claude/s1-datos`)

**Objetivo:** el camino OLAP deja de estar caído; el cursor PSCP queda verificado.

1. **`db/analytics.py` (249 líneas) → postgres_scanner.** Hoy `get_connection()`
   (`:97`) hace `ATTACH ... (TYPE SQLITE)` sobre `_sqlite_path()` (`:78`) que
   lanza `FileNotFoundError` siempre. Cambiar a
   `ATTACH '<DATABASE_URL>' AS ... (TYPE POSTGRES, READ_ONLY)` con
   `config.settings.DATABASE_URL`; eliminar `_sqlite_row_counts` (`:155`) y el
   uso de `_sqlite_path` en `run_analytics_export` (`:193`) sustituyéndolo por
   conteos vía la conexión Postgres. Callers a revisar (solo 2):
   `scheduler/kpi_precompute.py:276` y `scheduler/pipeline_runs.py:165`.
2. **Test de regresión** (AC del backlog): mockear `is_postgres_backend()=True`
   y verificar que NO se llama a `_sqlite_path()`. Marcar honesto: sin
   `postgres_scanner` real en CI, el test cubre el wiring, no la extensión —
   dejarlo dicho en el docstring.
3. **Verificación PSCP (observacional):** con las tools de GitHub MCP, leer los
   logs de los 2-3 últimos runs de `scrape-daily.yml` y confirmar que
   `pscp_fetch_start ... since=` (`scraper/connectors/pscp.py:257`) avanza entre
   runs. Reportar el resultado en el PR y cerrar (o re-priorizar) el ítem P2 del
   backlog según lo observado. **No tocar código del conector.**

**Archivos:** `db/analytics.py`, test nuevo en `tests/`.
**Verificación:** `make lint` + `make typecheck`; reportar que `make test-unit`
no corrió si no hay BD. Backlog: mover el ítem de `db/analytics.py` a Cerrados.
**Riesgo:** medio — sin Postgres+extensión real el cambio va parcialmente a
ciegas (documentado en el propio backlog); el PR debe decirlo.

---

### S2 — Radar de verdad (`claude/s2-radar`)

**Objetivo:** cerrar el P0/P1 de la página insignia: ranking real + dismiss
persistente + `pct_pyme` honesto.

1. **Migración v76 (gate pre-autorizado D3):** tabla `radar_dismissals`
   (`user_key TEXT NOT NULL`, `id_externo TEXT NOT NULL`, `created_at`,
   PK `(user_key, id_externo)`). Append-only, encadena
   `down_revision="v75_users_admin_granted_by"`. Patrón de referencia:
   `db/alembic/versions/v48_user_notifications.py`.
2. **Repositorio `db/radar_dismissals.py`** (SQL solo en `db/`, ADR-022):
   `add(user_key, id_externo)`, `remove(...)`, `list_ids(user_key)`. TODAS las
   queries con `AND user_key = ?` (no repetir el hueco de `db/watchlist.py`).
3. **Ruta nueva** (CRUD simple → `db.*` directo desde la ruta, ADR-024; sin capa
   de servicio): `api/routes/radar.py` con
   `GET/POST /api/v1/radar/dismissals` + `DELETE /api/v1/radar/dismissals/{id_externo}`,
   auth por sesión. Patrón a imitar: `api/routes/saved_filters.py` (helper
   `_user_key(ctx)` en `:36`, rutas `:71-110`). DTOs route-local (patrón
   `BulkGetResult` en `api/routes/licitaciones.py:834-849`) para no tocar
   `shared/dto.py`. Registrar router en `api/app.py`. **Nace tipada** (invariante
   §3.5: la allowlist de opacas está a cero y no puede crecer).
4. **`ScoredOpportunity` (`services/analytics/scoring.py:66`):** añadir
   `fecha_limite` y `tecnologia` **sin default** (nota de modelado del backlog),
   poblándolos en la query/ensamblado del scoring. Cambio aditivo de contrato.
5. **`web/src/hooks/use-radar.ts`:** la lista pasa a
   `GET /analytics/scoring?limit=24` como fuente del orden (el endpoint ya
   acepta `limit` y sesión — hecho verificado 1). Muere el merge listado+scores.
   Dismiss vía los endpoints nuevos con optimistic update.
6. **`radar/page.tsx`:** `dismissed` deja `React.useState` (`:79`, callback
   `:138`) y consume servidor; recargar conserva el triaje. Actualizar el copy
   de alcance: de "señales recientes" a ranking de mercado.
7. **`pct_pyme` honesto:** `services/analytics/overview.py:381` devuelve `0.0`
   hardcodeado. La columna `es_pyme` existe (`empresas`, INTEGER nullable) y
   `services/analytics/competitors.py:341` ya la calcula. Si el join con
   adjudicaciones da señal no-vacía → calcular real; si la columna está vacía en
   la práctica → **retirar el KPI del overview y su tile del frontend** (peor es
   mentir 0%). Documentar cuál de las dos ramas se tomó en el PR.
8. **Regenerar el cliente OpenAPI** (`web/src/generated/api.d.ts`) y tipar el
   consumo (`make check-api-contract`).

**Archivos:** migración v76, `db/radar_dismissals.py`, `api/routes/radar.py`,
`api/app.py` (registro), `services/analytics/scoring.py`,
`services/analytics/overview.py`, `web/src/hooks/use-radar.ts`,
`web/src/app/(dashboard)/radar/page.tsx`, tests nuevos.
**Verificación:** `make lint`/`typecheck`/`web-lint`/`web-typecheck` +
`make check-api-contract` + `make check-frontend-invariants`; tests de la ruta
(patrón de tests de `saved_filters`) correrán en CI del PR. Backlog: mover el
ítem P1 del Radar y el P3 de `pct_pyme` a Cerrados.
**Riesgo:** medio — única migración del plan y contrato aditivo.

---

### S3 — Frontend fixes (`claude/s3-frontend`)

**Objetivo:** controles que no mienten, tipos que no se inventan, i18n honesta.

1. **Multi-select real en `scope-bar.tsx`** (los 3 `<select value="">` en
   `:200`, `:219`, `:242`): sustituir por `Popover` (`ui/popover.tsx`) + lista con
   `Checkbox` (`ui/checkbox.tsx`) + búsqueda con `foldText`
   (`web/src/lib/utils.ts:170`) — "informatica" debe encontrar "Informática".
   Mirar `ui/search-autocomplete.tsx` antes de construir nada nuevo. El control
   muestra lo seleccionado y permite quitar desde sí mismo. El estado sigue en
   URL vía nuqs (no cambia).
2. **Derivar los 6 hooks del esquema generado** (`use-ask`, `use-organization`,
   `use-price-scenarios`, `use-source-freshness`, `use-tender-fact-sheet`,
   `use-watchlist-items` en `web/src/hooks/`): sus endpoints están todos tipados
   (hecho verificado 4). Sustituir cada `interface` local por
   `components["schemas"][...]` de `@/generated/api`. `make web-typecheck` es el
   guardián.
3. **Retirar i18n (D2):** eliminar `web/src/lib/i18n.ts` + `web/public/locales/`,
   inlineando las claves en los **8** ficheros que hoy usan `t()` (eran 12; ya
   solo 8). Ajustar tests que dependan de claves.

**Archivos:** `web/src/components/layout/scope-bar.tsx`, `web/src/hooks/*` (los
6), `web/src/lib/i18n.ts` (borrar), `web/public/locales/` (borrar), tests vitest.
**Verificación:** `make web-lint` + `make web-typecheck` + vitest (corre sin BD)
+ `make check-frontend-invariants`. Backlog: mover los ítems de scope-bar,
hooks tipados e i18n a Cerrados.
**Riesgo:** bajo.

---

### S4 — Seguridad/robustez (`claude/s4-seguridad`)

**Objetivo:** vaciar la parte crítica de los ratchets: auth observable, IDOR
cerrados, 500→4xx, `is_admin` con procedencia.

1. **IDOR user_key (3 funciones):** añadir `user_key` como parámetro y
   `AND user_key = ?` a: `db/watchlist.py::remove_entry` (`:71-73`),
   `db/watchlist.py::update_frequency` (`:123`),
   `db/saved_filters.py::delete_saved_filter`, y el
   `UPDATE watchlist_rules SET email` de `api/routes/watchlist_rules.py::post_rule._create`.
   Actualizar callers. Borrar las entradas de `_KNOWN_GAPS_PENDING_FIX`
   (`tests/test_user_key_sql_isolation.py:253`) — el ratchet falla si sobran.
2. **Excepciones tragadas — olas auth y auditoría** (12 de las 32 de
   `_GRANDFATHERED_PENDING_FIX`, `tests/test_swallowed_exceptions_guard.py:213`):
   las 5 de `db/repositories/api_keys.py`, `db/sessions.py::validate_session`,
   `db/totp.py::verify_totp` y `use_recovery_code`, `db/audit.py::log_event` y
   `verify_hash_chain`, y las 2 de export GDPR
   (`db/repositories/watchlist.py::export_items_by_user_key`,
   `db/repositories/audit.py::export_by_user_key`). Patrón: `log.warning("<evento>",
   exc_info=True)` antes del fallback; borrar cada entrada del frozenset. Las de
   búsqueda/analítica quedan para Ola 2.
3. **500→4xx (las 3 entradas de `KNOWN_5XX`,
   `scripts/fuzz_api_contract.py:112-117`):** decisión de diseño ya tomada por
   el backlog — validador Pydantic compartido para `\x00` en body (anclarlo en
   `shared/dto.py` y aplicarlo a `BulkGetRequest` y feature-flags) y manejo en
   frontera HTTP para `%ff` en path (en `api/middleware.py`, junto a los 5
   middlewares existentes, o exception handler de decodificación). Ambos
   devuelven 400/422. Vaciar `KNOWN_5XX` (validar con `--list` requiere BD
   sembrada: si no hay, dejarlo anotado para el CI/usuario).
4. **Cablear `admin_granted_by` (v75 ya migrada, columna inerte — hecho
   verificado 3):** `admin_users.admin_set_admin` escribe `'panel'`;
   `_sync_oauth_admin` (`api/routes/auth.py:688`) escribe `'oauth'` al promover
   y **solo degrada concesiones de origen `'oauth'`** (las de panel sobreviven
   al login de Google). Test del AC del backlog: promover desde panel + login
   OAuth sin ese email → flag se conserva. Actualizar el docstring de
   `_sync_oauth_admin` (dejará de ser cierto) y el ítem P2 del backlog.

**Archivos:** `db/watchlist.py`, `db/saved_filters.py`,
`api/routes/watchlist_rules.py`, `db/repositories/api_keys.py`, `db/sessions.py`,
`db/totp.py`, `db/audit.py`, `db/repositories/watchlist.py`,
`db/repositories/audit.py`, `shared/dto.py`, `api/middleware.py`,
`api/routes/auth.py`, `api/routes/admin_users.py`, los 2 tests-ratchet, tests
nuevos. (Toca `api/app.py` solo si el manejo `%ff` es middleware — rebasar tras S2.)
**Verificación:** `make lint`/`typecheck`; suite completa en CI del PR (los
tests de auth requieren BD). Backlog: mover ítems user_key, 500s y is_admin a
Cerrados; anotar progreso parcial (12/32) en el de excepciones.
**Riesgo:** medio — toca camino de auth; mitigado porque los cambios son
aditivos (logs) o restrictivos (predicados extra) y el CI corre la suite entera.

---

### S5 — Poda de navegación (`claude/s5-poda`)

**Objetivo:** D1 — el producto muestra sus 2-3 flujos de valor; lo no-core deja
de fingir paridad.

1. **Clasificar las ~35 páginas** de `web/src/lib/navigation.ts:85` (`SECTIONS`)
   + `space-views.ts` en tres grupos y proponerlo como tabla en el PR (el
   usuario aprueba ahí la lista final):
   - **Core** (propuesta inicial): radar, oportunidades, detalle, mi-pipeline,
     mi-watchlist, resumen, competidores(+empresa), calendario, mi-perfil.
   - **Admin** (visible solo `is_admin`): administracion, feature-flags,
     observabilidad, ops, calidad-datos, equipo, active-learning.
   - **Experimental** (fuera de la navegación; accesible por URL con banner
     "experimental"): clusters, red-organo-empresa, ecosistema-partners,
     proyectos-modulos, utes, geografia, tendencias-cpv, tendencias, mercado,
     organos, empresas, renovaciones, investigador, pipeline-alertas, etc.
2. **Implementar el mecanismo**, no 35 excepciones: campo `visibility:
   "core" | "admin" | "experimental"` en `NavPage`/`NavSection`; sidebar y
   command-palette filtran por él; banner común en páginas experimentales.
3. **No borrar código ni rutas** (D1). No tocar redirects existentes
   (`/licitadores` → `/competidores` se queda).

**Archivos:** `web/src/lib/navigation.ts`, `web/src/lib/space-views.ts`,
componentes de sidebar/command-palette que consumen SECTIONS, banner nuevo,
tests de navegación existentes.
**Verificación:** `make web-lint`/`web-typecheck` + vitest; E2E de navegación en
CI. **El PR lista la clasificación en su descripción para aprobación explícita.**
**Riesgo:** bajo-medio — mucha visibilidad, cero borrado.

---

### S6 — Infra de verificación (`claude/s6-infra`)

**Objetivo:** que el contribuidor principal (los agentes) pueda correr los tests
donde desarrolla, y que la suite de CI no roce su techo de tiempo.

1. **Postgres en sesiones remotas (gate deps pre-autorizado D3):** hook
   `SessionStart` en `.claude/settings.json` (hoy solo hay 2 PreToolUse) +
   script `.claude/hooks/session_start_pg.sh` que: instala/arranca un Postgres
   local efímero (apt `postgresql` + `postgresql-<v>-pgvector`; si no hay red
   apta, degradar con mensaje claro), crea rol/DB de test, exporta
   `TEST_DATABASE_URL` (formato exacto que exige `tests/conftest.py:183-188`) y
   habilita `pg_trgm` + `vector`. Usar el skill `session-start-hook` como guía.
   AC: en una sesión remota fresca, `make test-unit` corre de verdad.
   Documentar en `docs/AGENT_PLAYBOOK.md` y actualizar la advertencia de
   `CLAUDE.md` (sección "Sesiones remotas") — hoy dice que los tests no corren.
2. **`-n auto` en CI (gate workflows pre-autorizado D3):** `pytest-xdist` y el
   fixture xdist-safe ya están (backlog, progreso 2026-08-03). Cambiar
   `.github/workflows/ci.yml:141` a `pytest -n auto --cov=...`, medir duración
   del job antes/después en el PR, y si el aislamiento falla, revertir a serie
   (el fallback documentado).

**Archivos:** `.claude/settings.json`, `.claude/hooks/session_start_pg.sh`
(nuevo), `.github/workflows/ci.yml:141`, `docs/AGENT_PLAYBOOK.md`, `CLAUDE.md`.
Si toca customizaciones de agentes: `make check-agent-docs` (y paridad
`.agents/` si aplica).
**Verificación:** el propio hook en una sesión remota nueva; CI verde con
tiempos comparados en la descripción del PR. Backlog: cerrar el ítem `-n auto`.
**Riesgo:** medio en el hook (entorno remoto variable — degradar con gracia),
bajo en CI (fallback trivial).

---

## Ola 2 — tras el merge completo de la Ola 1

Secuencial o paralela según conflicto; cada ítem hereda las reglas de
verificación de arriba:

1. **Retirar el shim qmark** (`db/connection.py::_translate_qmarks` +
   `_PgConnAdapter`): 1.123 `?` en 57 archivos, por olas de archivos con suite
   verde entre olas (AC del backlog). Necesita el árbol quieto: por eso es Ola 2.
2. **UI de webhooks + GDPR self-service** (2 páginas; backend completo en
   `api/routes/webhooks.py` y `api/routes/me.py`): CRUD + ping + secret una vez
   + estado de entregas; export `/me/data` y delete de cuenta con confirmación.
   Entra en navegación como `core`/`admin` según S5.
3. **Excepciones tragadas restantes** (~20: búsqueda, analítica) — mismo patrón S4.
4. **El resto del backlog ya priorizado** (MRR retrieval ≥0.75, fixtures CODICE
   reales, umbrales de auditoría, tooltips, ortografía): siguen en
   `docs/IMPROVEMENT_BACKLOG.md`; este plan no los duplica.

## Reglas de verificación comunes (todos los streams)

- Sesión remota sin BD (hasta que S6 aterrice): correr `make lint` +
  `make typecheck` (+ `web-lint`/`web-typecheck`/vitest en frontend) y
  **declarar en el PR qué controles no corrieron** (AGENTS.md §4). El gate real
  es el CI del PR (Postgres + suite + E2E bloqueante + fuzz).
- Cambio analítico frontend → `make check-frontend-invariants`. Cambio de
  contrato → `make check-api-contract`. Tocar AGENTS/customizaciones →
  `make check-agent-docs`.
- Cada ratchet parcialmente vaciado encoge su allowlist **en el mismo PR**.
- Cada stream mueve sus ítems del backlog a Cerrados en el mismo PR (o anota
  progreso parcial).
- Ningún stream crea RFCs ni ADRs nuevos salvo que caiga en los 4 supuestos de
  la política de AGENTS.md §5 (ninguno de este plan lo hace).
- Commits sin `--no-verify`; `graphify update` se omite en remoto (CLI no
  disponible) y se deja el flag stale que los hooks generan (comportamiento
  documentado como normal).

## Qué NO hace este plan

- No borra páginas, tests ni RFCs históricos (D1; AGENTS.md §6).
- No toca el checklist manual de hardening Supabase (P1 del backlog): son
  acciones del usuario contra infraestructura real con credenciales que un
  agente no tiene.
- No implementa presupuesto/circuit-breaker LLM (RFC propio ya existente) ni la
  migración de identidad a SQL con `unaccent` (P3, requiere extensión nueva —
  gate no pre-autorizado).
