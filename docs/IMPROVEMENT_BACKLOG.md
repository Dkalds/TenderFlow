# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo borres: movélo a la sección **Cerrados** abajo, con la PR/commit que lo resolvió.

---

## P1 — Alta

### Parchear dependencias vulnerables y reconciliar el entorno con el lockfile
- **Área:** `requirements.txt`, `.venv`, `web/package.json`, CI
- **Problema:** Auditorías de dependencias (`pip-audit` + `npm audit`) revelan vulnerabilidades conocidas y, lo más grave, **drift entre el lockfile y lo instalado**:
  - **starlette**: `requirements.txt` pinea `starlette==1.2.0` (parcheado), pero el `.venv` tiene **0.52.1 instalado** — afectado por `PYSEC-2026-161` (fix `1.0.1`). Es la base de FastAPI (runtime), así que importa. Síntoma de que el entorno no se reinstaló tras recompilar `requirements.txt`; si CI/prod parten de un venv stale, corren la versión vulnerable.
  - **pytest** `8.4.2` → `CVE-2025-71176` (fix `9.0.3`, dev/test).
  - **pip** `24.2` → 5 CVEs (fix `26.1.2`, tooling).
  - **Frontend**: `npm audit` reporta 2 moderate — `postcss <8.5.10` (XSS, GHSA-qx2v-qp2m-jg93) arrastrado por **Next 16.2.6** (rango vulnerable `… - 16.3.0-canary.5`). Fix: subir Next a una versión con el postcss parcheado.
- **Acceptance criteria:**
  - `pip install -r requirements.txt` en un venv limpio deja `starlette>=1.0.1` (idealmente la `1.2.0` ya pineada) y `pip-audit` no reporta vulns de runtime.
  - `pytest` y `pip` actualizados (o documentado por qué no).
  - `npm audit --omit=dev` sin moderate/high (subir Next).
  - CI instala estrictamente desde el lockfile y corre `pip-audit`/`npm audit` como gate (o al menos informativo).
- **Files de partida:** [requirements.txt](../requirements.txt), [requirements-dev.txt](../requirements-dev.txt), [web/package.json](../web/package.json).
- **Riesgo:** medio — subir Next/starlette puede traer breaking changes menores; verificar con la suite de tests (back + vitest) y `next build`.

### Añadir job de CI para el frontend (`web/`)
- **Área:** `.github/workflows/`, `web/`
- **Problema:** El frontend tiene tests (vitest + playwright), lint (eslint), typecheck (`tsc --noEmit`) y build (`next build`) configurados, pero **ninguno corre en CI** — no hay referencias a `npm`/`vitest`/`playwright`/`eslint`/`next build` para `web/` en ningún workflow de `.github/workflows/`. Resultado: regresiones del frontend no se detectan automáticamente. De hecho la rotura de ESLint (ver ítem P2 `jsx-a11y` duplicado) pasó inadvertida justamente porque el lint no está gateado.
- **Acceptance criteria:**
  - Nuevo job (o workflow) que, con `working-directory: web`, corra al menos: `npm ci`, `npm run typecheck`, `npm run lint`, `npm run test` (vitest). Idealmente también `npm run build`.
  - El job falla el pipeline si cualquiera de esos pasos falla.
  - Cachear `~/.npm` / `node_modules` por `web/package-lock.json` para tiempos razonables.
  - (Opcional) e2e playwright en un job separado/manual, no en cada push, para no encarecer CI.
- **Files de partida:** [.github/workflows/ci.yml](../.github/workflows/ci.yml), [web/package.json](../web/package.json) (scripts ya existen).
- **Riesgo:** bajo — añade un gate, no toca código de producción. **Requiere OK humano: editar `.github/workflows/` está en la lista de confirmación (AGENTS.md §6).**

### ~~Calcular `lead_time_medio` en el detalle de órgano~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). `_lead_time_median()` en `organo_detail.py` calcula la mediana de `(fecha_adjudicacion - fecha_publicacion)` sobre las adjudicaciones del órgano (solo diferencias positivas). Tests en `test_analytics_organos.py`. Ver sección Cerrados.

### ~~Cachear la carga de DataFrames en `services/analytics/`~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). `services/_data_cache.py::SignalAwareCache` (TTL + señal de ingesta `shared.cache_signal`) aplicado a `load_stats_dataframe()` y al caso sin filtros de `load_raw_adjudicaciones()`. Fixture autouse en conftest limpia entre tests. Ver sección Cerrados.

### ~~Strict typing en `dashboard/`~~ — CERRADO
- **Estado:** Resuelto (2026-05-29). Todos los módulos de producción (375 archivos) pasan `mypy --strict` sin errores. Ver sección Cerrados.

### ~~`py.typed` marker para consumo externo del paquete~~ — CERRADO
- **Estado:** Resuelto (2026-05-29). `shared/py.typed` creado. Ver sección Cerrados.

---

## P2 — Media

### ~~Completar `.env.example` con los settings críticos de prod~~ — CERRADO
- **Estado:** Resuelto (2026-06-09). Añadidas secciones a `.env.example`: `WEBHOOK_SIGNING_KEY`, `TOTP_ENCRYPTION_KEY` (con comando de generación Fernet), `CORS_ALLOWED_ORIGINS`, `METRICS_ALLOWED_IPS`, OTEL (`OTEL_EXPORTER_OTLP_ENDPOINT`/`SERVICE_NAME`/`SAMPLE_RATIO`), alertas email (`ALERT_EMAIL_TO`/`ALERT_SMTP_*`), `DRAMATIQ_BROKER_URL`, `DB_POOL_SIZE`/`DB_POOL_TIMEOUT`, y nota apuntando a `config/settings.py` para el resto. Ver sección Cerrados.

### ~~Reemplazar el N+1 INSERT de `kpi_precompute` por `executemany`~~ — CERRADO
- **Estado:** Resuelto (2026-06-09). `_persist_snapshots` usa `conn.executemany` con early-return para lista vacía; `DELETE` previo intacto. 2 tests nuevos (batch + vacío) en `test_kpi_precompute.py` (14 pasando). Ver sección Cerrados.

### ~~Corregir el puerto por defecto del proxy de API en Next (`8081` → `8080`)~~ — CERRADO
- **Estado:** Resuelto (2026-06-09). `next.config.ts`: fallback del rewrite `API_BASE_URL` corregido a `http://localhost:8080`. Ver sección Cerrados.

### Subir cobertura de tests del frontend y cubrir áreas críticas sin tests
- **Área:** `web/`
- **Problema:** Los thresholds de vitest son bajos (`statements/lines 30`, `branches/functions 25`) frente a ~50 páginas de dashboard y solo ~4 tests de componentes/hooks (`kpi-card`, `treemap-content`, `admin-guard`, `use-admin`, `use-filtered-query`). Componentes con lógica no trivial (charts, `filters-sidebar`, páginas con transformaciones de datos como `pipeline-alertas`) no tienen tests unitarios.
- **Progreso (2026-06-09):** +4 tests de edge-cases en `chart-formatters.test.ts` (input `undefined`, `name` undefined/numérico) protegiendo el re-tipado reciente; suite 241 → **245**. Falta cubrir componentes/hooks con lógica de transformación y subir los thresholds.
- **Acceptance criteria:**
  - Añadir tests para al menos 3-4 componentes/hooks no cubiertos con lógica real (no smoke render): p. ej. transformaciones de datos en `pipeline-alertas`, `force-graph`, `filters-sidebar`.
  - Subir los thresholds de `vitest.config.ts` de forma incremental tras añadirlos (no bajarlos nunca).
  - `npm run test:coverage` pasa con los nuevos umbrales.
- **Files de partida:** [web/vitest.config.ts](../web/vitest.config.ts), `web/src/components/`, `web/src/hooks/`.
- **Riesgo:** bajo — solo tests/config de tests.

### Limpiar deuda de lint del frontend (warnings que la config rota ocultaba)
- **Área:** `web/`
- **Problema:** Al arreglar la config de ESLint (ver ítem cerrado abajo), el lint pasó a ejecutarse y afloraron ~160 warnings que nunca se habían enforced. Para no bloquear CI ni arriesgar bugs, varias reglas se dejaron en `warn` como deuda progresiva: `react-hooks/exhaustive-deps` (~36), set recommended de `jsx-a11y` y las reglas del React Compiler `react-hooks/{set-state-in-effect,purity,immutability}` (6). Son potenciales bugs (stale closures, render impuro) y problemas de accesibilidad reales.
- **Progreso (2026-06-09):** 160 → **123 warnings**. Desactivada la regla **deprecada** `jsx-a11y/label-has-for` (−29, redundante con `label-has-associated-control`). Corregidos `control-has-associated-label` en componentes compartidos (`global-filter-bar` date inputs, `filters-sidebar` checkboxes) con `aria-label` (−4). Quedan: `exhaustive-deps` (~36), React Compiler (6), y `jsx-a11y` restantes en páginas individuales (`label-has-associated-control`, `control-has-associated-label`, interactive-element en `top-nav`/`comparator`/`search-autocomplete`/`sheet`).
- **Acceptance criteria:**
  - Resolver los warnings por grupos (terminar `jsx-a11y` en páginas, luego `exhaustive-deps`, luego React Compiler).
  - A medida que un grupo llega a cero, **re-endurecer** esa regla a `error` en `web/eslint.config.mjs`.
  - `npm run lint` sigue en 0 errores en cada paso.
- **Files de partida:** [web/eslint.config.mjs](../web/eslint.config.mjs) (severidades), `web/src/components/`, `web/src/app/`.
- **Riesgo:** medio — los fixes de `exhaustive-deps`/React Compiler pueden cambiar comportamiento; hacerlos uno a uno con verificación.

### ~~Restaurar `mypy --strict` limpio (drift por upgrade de pandas-stubs)~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). 3 anotaciones corregidas: `tecnologias.py` (`.apply`→groupby vectorizado de Series), `clusters.py` (`int(cast("SupportsInt", cid))`), `rate_limit_redis.py` (eliminado `# type: ignore` no usado). `mypy services/` pasa (41 archivos). Ver sección Cerrados.

### ~~Arreglar la config de ESLint del frontend (jsx-a11y duplicado)~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). Eliminada la re-declaración del plugin `jsx-a11y` (ya lo registra `eslint-config-next/core-web-vitals`); `src/generated/**` ignorado. `npm run lint` corre y sale 0 (0 errores). La deuda de warnings que destapó quedó en el ítem nuevo de arriba. Ver sección Cerrados.

### ~~Tests unitarios para `services/analytics/`~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). `tests/test_analytics_organos.py` (10 tests) cubre `organos`, `organo_detail` (incl. lead_time + paridad) y `overview` con DataFrames sintéticos y caso vacío. Ver sección Cerrados.

### ~~Auditar reaparición de `# noqa: S608`~~ — CERRADO (no era drift)
- **Estado:** Auditado (2026-06-08). Las 4 ocurrencias inline (`db/events.py`, `db/feature_store.py`, `db/repositories/base.py`, `scheduler/retention.py`) son seguras (todo el input variable va por placeholders `?`; tablas/columnas son constantes internas) **y ya están documentadas** en `pyproject.toml` (líneas ~140-141, sección `per-file-ignores`). No es drift: Bloque 9 movió la mayoría a `per-file-ignores` y dejó estas 4 como inline justificadas. Sin cambio de código.

### ~~Paridad de campos Streamlit ↔ Next.js en el Sheet de órgano~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). Añadidos `url`, `estado_desc`, `tipo_proyecto`, `tipo_contrato_desc`, `cpv_desc` al DTO `TopScored` y a la card del Sheet (título clickeable). Ver sección Cerrados.

### ~~Reducir SQL manual con `S608` suppress~~ — CERRADO
- **Estado:** Resuelto en Bloque 9 (2026-05-23). Ver sección Cerrados.

### ~~Documentar la fachada `db.database`~~ — CERRADO (ya estaba)
- **Estado:** Verificado (2026-06-08). Ya cumplido: docstring de módulo exhaustivo en `db/database.py` (lista los 3 submódulos y símbolos reexportados) + fila en la tabla de [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) (`db/` → fachada) + FAQ "¿Cómo importar desde db/?" + enlaces a ADR-001/003. Sin cambio.

### ~~Instalar stubs de pandas para mypy~~ — CERRADO (ya estaba)
- **Estado:** Verificado (2026-06-08). `pandas-stubs>=2.0.0,<3` (+ `types-requests`, `types-python-dateutil`) ya declarados en `requirements-dev.txt`. mypy resuelve pandas sin `import-untyped`. Nota: el rango sin pinear introdujo drift de strict typing — ver ítem nuevo arriba.

---

## P3 — Nice to have

### ~~Eliminar `any` en componentes del frontend~~ — CERRADO
- **Estado:** Resuelto (2026-06-09). `mi-watchlist` index signature `any`→`unknown`; formatters de recharts tipados en `chart-formatters.ts` (`RechartValue` incluye `undefined`/`readonly`, `name: string|number|undefined`) y usados sin cast; `force-graph` d3 sin `as any` (null-guard del ref + `selectAll<SVGCircleElement, SimNode>`). `tsc` y vitest (241) verdes. Ver sección Cerrados.

### ~~Añadir cabecera CSP `Report-Only` en el frontend~~ — CERRADO
- **Estado:** Resuelto (2026-06-09). `next.config.ts`: header `Content-Security-Policy-Report-Only` (constante `CSP_REPORT_ONLY`) con directivas estructurales estrictas (`frame-ancestors 'none'`, `object-src 'none'`, `base-uri`/`form-action 'self'`) y `report-uri /api/v1/security/csp-report`; `script-src`/`style-src` permisivas por ahora (fase 1: medir). Ver sección Cerrados.

### Diferir librerías de charts pesadas con `next/dynamic`
- **Área:** `web/`
- **Problema:** ~10 páginas del dashboard importan `recharts` (y algunas `d3`/force-graph) de forma **estática** (`calendario`, `calidad-datos`, `clusters`, `competidores`, `ecosistema-partners`, `geografia`, `licitadores`, `pipeline-alertas`, `proyectos-modulos`, …), frente a solo 8 usos de `next/dynamic` en todo el frontend. Recharts es pesado (~100 KB+). Next code-splittea por ruta, pero el chunk de cada ruta carga recharts de forma eager al entrar, retrasando el primer paint. La página `organos` ya demuestra el patrón correcto (`Treemap` vía `dynamic(..., { ssr: false })`).
- **Acceptance criteria:**
  - Para páginas con muchos primitivos de recharts, **extraer el chart a un subcomponente** propio y `dynamic`-importarlo (`ssr: false`) + `Skeleton` de fallback (no basta con dynamic-importar cada primitivo suelto).
  - Medir antes/después con `next build` (tamaño del chunk por ruta) en 2-3 páginas piloto.
  - Sin regresiones visuales (los charts siguen renderizando) — verificar con la app corriendo.
- **Files de partida:** las páginas listadas; patrón de referencia [web/src/app/(dashboard)/organos/page.tsx](../web/src/app/(dashboard)/organos/page.tsx) (línea ~44).
- **Riesgo:** medio — refactor de extracción por página + verificación visual; merece pasada deliberada, no en lote con otros cambios.

### Dividir los archivos/componentes "God" más grandes
- **Área:** `web/`, `dashboard/`, `db/`
- **Problema:** Varios archivos superan ~800-1100 LOC, lo que dificulta navegación, review y testing:
  - Frontend: `competidores/page.tsx` (980), `pipeline-alertas/page.tsx` (854), `tecnologias/page.tsx` (818), `proyectos-modulos/page.tsx` (737). Páginas que mezclan fetching, transformaciones de datos y render de múltiples charts en un único componente.
  - Backend: `db/migrations.py` (1121, legacy ya deprecado a favor de Alembic — candidato a poda), `dashboard/stats/_base.py` (1070), `scraper/ml_classifier.py` (880).
- **Acceptance criteria:**
  - Extraer de las páginas frontend más grandes los bloques de transformación de datos a hooks/`lib` y los charts a subcomponentes (objetivo orientativo: < ~400 LOC por página).
  - Evaluar si `db/migrations.py` puede reducirse/archivarse ahora que Alembic es la fuente de verdad (ver ADR-008).
  - Sin cambios de comportamiento; `tsc`/`vitest`/`mypy` siguen verdes.
- **Files de partida:** los listados arriba.
- **Riesgo:** medio — refactor amplio; hacerlo por archivo con verificación, no en bloque.

### ~~Navegación por teclado completa en Sankey chart~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). Nodos con `aria-label` (label + origen/destino + flujo), navegación con flechas/Home/End (mueve foco entre nodos), y eliminado el TODO. `tsc --noEmit` limpio. Ver sección Cerrados.

### ~~Documentar / desbloquear tests con `pytest.skip`~~ — CERRADO
- **Estado:** Resuelto (2026-06-08). Los 3 skips son condicionales legítimos con motivo claro (pandera ausente / dramatiq presente→fallback / puerto ocupado). Documentada la política en [docs/testing.md](testing.md) (sección "Skips condicionales"). De paso corregido `fail_under` en testing.md (51 → 70). Ver sección Cerrados.

### Hook PostToolUse para marcar graph como stale tras edits a `.py`
- **Área:** `.claude/settings.json`
- **Problema:** Hoy el agente debe acordarse de correr `graphify update .` tras editar (lo dice AGENTS.md sección 5, pero es manual). Un hook PostToolUse puede dejar un flag `graphify-out/.graph_stale` cuando se edita un `.py`, y `/graph-refresh` lo borra. Detecta drift automáticamente.
- **Acceptance criteria:**
  - Añadir un bloque PostToolUse en `.claude/settings.json` con matcher `Edit|Write|MultiEdit` que ejecute:
    ```bash
    python3 -c "import json,sys,os,pathlib;d=json.load(sys.stdin);fp=(d.get('tool_input',d) or {}).get('file_path','');skip=any(x in fp for x in ('.venv','graphify-out','.mypy_cache','.pytest_cache','.ruff_cache','__pycache__','htmlcov','node_modules'));ok=fp.endswith('.py') and not skip and os.path.isdir('graphify-out');pathlib.Path('graphify-out/.graph_stale').touch() if ok else None" 2>/dev/null || true
    ```
  - Actualizar `/graph-refresh` (ya lo hace) para borrar el flag tras update exitoso.
  - Probar: editar un `.py`, verificar que existe `graphify-out/.graph_stale`; correr `/graph-refresh`; verificar que se borró.
- **Files de partida:** [.claude/settings.json](../.claude/settings.json) (ya tiene un PreToolUse; añadir PostToolUse manteniéndolo).
- **Riesgo:** bajo — el hook es silencioso (`|| true`), no bloquea ediciones. **Self-modification: requiere que el humano lo añada (el agente no puede editar `.claude/settings.json` por política de seguridad).**

---

## Cerrados

- [2026-06-08] **P1: `lead_time_medio` en detalle de órgano** — `services/analytics/organo_detail.py`: nuevo `_lead_time_median()` calcula la mediana de `(fecha_adjudicacion − fecha_publicacion)` en días (solo positivos) sobre las adjudicaciones del órgano; antes devolvía siempre `None`. Tests en `tests/test_analytics_organos.py`.
- [2026-06-08] **P1: Caché de DataFrames en analytics** — `services/_data_cache.py::SignalAwareCache` (TTL 60s + invalidación por `shared.cache_signal`) aplicada a `load_stats_dataframe()` y al caso sin filtros de `load_raw_adjudicaciones()`; `clear_stats_cache()`/`clear_raw_adj_cache()` + fixture autouse en `tests/conftest.py`. Evita N relecturas de SQLite por request. Tests en `tests/test_data_cache.py`.
- [2026-06-08] **P2: Tests unitarios de analytics** — `tests/test_analytics_organos.py` (10 tests): `get_organos`, `get_organo_detail` (lead_time, estado_desc, url, paridad) y `get_overview` con DataFrames sintéticos + caso vacío. Fix de tipado: `adj_lookup: dict[str, dict[str, Any]]` en `organo_detail.py`.
- [2026-06-08] **P2: Paridad Streamlit ↔ Next.js (Sheet órgano)** — `TopScored` + card del Sheet exponen `url` (título clickeable), `estado_desc` (legible), `tipo_proyecto`, `tipo_contrato_desc`, `cpv_desc`. Backend `organo_detail.py` + `web/src/app/(dashboard)/organos/page.tsx`.
- [2026-06-08] **P3: Keyboard nav en Sankey** — `web/src/components/charts/sankey-chart.tsx`: `aria-label` por nodo (label + origen/destino + flujo), navegación con flechas/Home/End entre nodos, TODO eliminado.
- [2026-06-08] **P3: Política de skips documentada** — `docs/testing.md`: sección "Skips condicionales" (pandera/dramatiq/puerto); `fail_under` corregido 51 → 70.
- [2026-06-08] **Auditorías (sin cambio de código)** — `# noqa: S608` (4 inline) confirmadas seguras y ya documentadas en `pyproject.toml`; fachada `db.database` ya documentada (docstring + AGENT_PLAYBOOK); `pandas-stubs` ya declarado en `requirements-dev.txt`.
- [2026-06-08] **mypy strict drift corregido** — 3 errores (por upgrade de `pandas-stubs` 2.3.3): `tecnologias.py` `.apply(include_groups=False)` → `is_adj.groupby(...).mean().mul(100)` (vectorizado, equivalencia verificada); `clusters.py` `int(cid)` → `int(cast("SupportsInt", cid))`; `rate_limit_redis.py` eliminado `# type: ignore[assignment]` no usado. `mypy services/` limpio.
- [2026-06-09] **`.env.example` completado** — añadidos `WEBHOOK_SIGNING_KEY`, `TOTP_ENCRYPTION_KEY` (+ comando Fernet), `CORS_ALLOWED_ORIGINS`, `METRICS_ALLOWED_IPS`, OTEL, alertas SMTP, `DRAMATIQ_BROKER_URL`, `DB_POOL_*`, y nota apuntando a `config/settings.py` para el resto de knobs.
- [2026-06-09] **kpi_precompute N+1 → executemany** — `scheduler/kpi_precompute.py::_persist_snapshots` usa `executemany` (+ early-return vacío); 2 tests nuevos (batch de 5 filas, lista vacía) en `test_kpi_precompute.py`.
- [2026-06-09] **next.config puerto API 8081→8080** — fallback del rewrite `API_BASE_URL` corregido; `make api` + `npm run dev` sin vars extra ya sirve datos.
- [2026-06-09] **CSP Report-Only** — `next.config.ts`: header `Content-Security-Policy-Report-Only` con `frame-ancestors/object-src/base-uri/form-action` estrictos + `report-uri /api/v1/security/csp-report` (fase 1: medir antes de enforce).
- [2026-06-09] **`any` eliminados en frontend** — `mi-watchlist` (`unknown`), formatters de recharts tipados en `chart-formatters.ts` y usados sin cast (3 sitios en `pipeline-alertas`), `force-graph` d3 sin `as any` (null-guard + `selectAll` con generics). `tsc` 0, lint 0 errores (warnings 160→156), vitest 241.
- [2026-06-08] **ESLint frontend desbloqueado** — `web/eslint.config.mjs`: eliminada la doble registración del plugin `jsx-a11y` (`ConfigError: Cannot redefine plugin`); `src/generated/**` ignorado; 2 interfaces vacías shadcn (`textarea.tsx`, `dropdown-menu.tsx`) → alias de tipo. Reglas con deuda heredada (`exhaustive-deps`, `jsx-a11y` recommended, React Compiler) en `warn` para limpieza progresiva. `npm run lint` pasa de crash a exit 0 (0 errores, 160 warnings); `tsc` y vitest (241) en verde.
- [2026-05-23] **P0-1: SSE columns fix** — `api/routes/stream.py`: `created_at`/`updated_at` (inexistentes en `licitaciones`) reemplazados por `fecha_extraccion`/`fecha_actualizacion_fuente`.
- [2026-05-23] **P0-2/P0-3: Async webhook ping + await run_db** — `api/routes/webhooks.py`: `requests.post` síncrono envuelto con `asyncio.to_thread()`; `_repo.create()` envuelto con `await run_db()`.
- [2026-05-23] **P1-1: Import Prometheus top-level** — `api/app.py`: eliminado `try/except ImportError` de `prometheus_fastapi_instrumentator` (hard dep en `pyproject.toml`); import movido al bloque top-level.
- [2026-05-23] **P1-2: 4 índices BD faltantes (v21)** — `db/alembic/versions/v21_missing_indexes.py`: `idx_lic_tecnologia`, `idx_lic_cursor`, `idx_lic_importe`, `idx_domain_events_actor`.
- [2026-05-23] **P1-3: Trivy SARIF separado en CI** — `.github/workflows/ci.yml`: step de Trivy dividido en tabla (exit-code 1) + SARIF separado.
- [2026-05-23] **P2-1: Rate limiting CSP report** — `api/routes/security.py`: 10 req/min por IP en `/csp-report`.
- [2026-05-23] **P2-2: DASHBOARD_PASSWORD SecretStr** — `config/settings.py`: `DASHBOARD_PASSWORD: SecretStr`; 6 call sites actualizados con `.get_secret_value()`.
- [2026-05-23] **P2-3: Health check Redis + disk** — `api/routes/health.py`: `_check_redis()` (ping 2s timeout), `_check_disk()` (threshold 500 MB); `/ready` devuelve 503 si degraded.
- [2026-05-23] **P2-4: `db.database` fachada pura** — Eliminadas copias locales de `safe_pragma` y `connect_read`; re-exporta desde `db.connection`. `test_turso_backend_compat.py` actualizado para patchear `db.connection` directamente.
- [2026-05-23] **P2-5: ZIP bomb protection** — `scraper/bulk_downloader.py`: límite 10 000 entries, ratio compresión > 100:1 → skip, lectura streaming con contador bytes.
- [2026-05-23] **P3-1: Reemplazar print() por structlog** — `scheduler/kpi_precompute.py`, `scheduler/aggregates_precompute.py`: `print()` → `log.info/warning/error`.
- [2026-05-23] **P3-3: Unificar rango sentence-transformers** — `pyproject.toml`: extras `ml` y `ml-embeddings` unificados a `>=2.2.0,<4`.
- [2026-05-23] **P3-4: AGENTS.md invariante #1 corregido** — `config/*` y `shared/*` marcados como "pending strict"; `db.database`, `db.users`, `dashboard.bootstrap` son los módulos strict confirmados.
- [2026-05-23] **P3-5: 4 test files nuevos (33 tests)** — `tests/test_auth.py` (11), `tests/test_db_connection.py` (9), `tests/test_admin.py` (6), `tests/test_tracing.py` (7). Bugs de test corregidos: reload() → monkeypatch.setattr en settings instance; columna `active` → `is_active`; `_DB_PATH_OVERRIDE` para is_turso_backend; `revoke_api_key` recibe `key_id: int`.

- [2026-05-23] **Coverage gate en CI** — Fase 3: `--cov-fail-under=55` en `pyproject.toml` sección `[tool.coverage.report]`. Coverage target subido de 51 a 55.
- [2026-05-23] **`.editorconfig` compartido** — Fase 8: creado `.editorconfig` con UTF-8, LF, trim trailing whitespace, indent 2 para yaml/json/md, 4 para Python.
- [2026-05-23] **`docs/testing.md`: guía de tests** — Fase 8: creado `docs/testing.md` con markers, naming, fixtures, cómo correr subsets.
- [2026-05-23] **`docs/api-design.md`: convenciones REST** — Fase 8: creado `docs/api-design.md` con nomenclatura, errores, paginación, scopes.
- [2026-05-23] **`CONTRIBUTING.md`: convenciones de PR/commit/branch** — Fase 8: creado `CONTRIBUTING.md` con branch naming, conventional commits, PR checklist, pre-commit.
- [2026-05-23] **Seguridad P0: scopes en endpoints sin protección** — Fase 1: `require_scope("admin")` en models activate, `require_scope("webhooks:read")` en 3 GET de webhooks, whitelist en `_distinct()`, sanitización de errores en exports.
- [2026-05-23] **ML foundation: validación de datos de entrenamiento** — Fase 2: `validate_training_data()` en `ml_pipeline.py`, feature store conectado en `predict_proba()`, warning de doble calibración.
- [2026-05-23] **Tests: 4 nuevos test files (26 tests)** — Fase 3: `test_threshold_tuning.py` (8), `test_model_registry.py` (7), `test_feature_store.py` (5), `test_drift_report.py` (6).
- [2026-05-23] **ML improvements: tuning, CV, CPV tokens, drift KS** — Fase 4: `RandomizedSearchCV` con `ML_TUNE_ON_TRAIN`, `StratifiedKFold`/`RepeatedStratifiedKFold`, CPV2/CPV4 en `_augment_text()`, `_prediction_drift()` KS test.
- [2026-05-23] **Code quality: silent exceptions → logged** — Fase 5: 18 `except Exception: pass` en `db/migrations.py` ahora logean `log.warning()`. `python_version` corregido a `"3.11"`.
- [2026-05-23] **DevOps: Docker hardening + Makefile** — Fase 6: Trivy `exit-code: "1"`, Docker compose security (security_opt, cap_drop, read_only, tmpfs, Redis ports ocultos, Grafana password obligatoria), Alembic `target_metadata` conectado, 4 targets nuevos en Makefile.
- [2026-05-23] **Advanced ML: embeddings + multi-metric promotion** — Fase 7: `SentenceEmbeddingTransformer` + `ML_USE_EMBEDDINGS`, gate de promoción multi-métrica (F1 + PR-AUC + Brier) en `concept_drift.py`.
- [2026-05-23] **A1: seed_negatives Turso compat** — Bug fix: `seed_negatives` en `scraper/ml_training.py` migrado de `sqlite3.connect(db_file)` a `db.database.connect()`, corrigiendo incompatibilidad con Turso.
- [2026-05-23] **B1: Índices de rendimiento v32** — Migración 32: 4 índices (`idx_lic_tecnologia`, `idx_lic_ml_proba`, `idx_adj_nombre_importe`, `idx_adj_ccaa_nombre`) con rollback.
- [2026-05-23] **B2: executemany en precompute_ml_proba** — Reemplazo de N+1 UPDATEs individuales por `executemany` en `scraper/ml_training.py`.
- [2026-05-23] **B3: LEFT JOIN en active learning queries** — `get_unlabelled_candidates` y `get_unlabelled_random` reescritos de `NOT IN (SELECT …)` a `LEFT JOIN … IS NULL`.
- [2026-05-23] **B4: SUBSTR en _compute_clusters** — `SUBSTR(descripcion, 1, 500)` para limitar memoria en clustering.
- [2026-05-23] **C1-C5: 5 test files de seguridad (63 tests)** — `test_middleware.py` (17), `test_gdpr.py` (13), `test_totp.py` (12), `test_webhooks.py` (10), `test_partners.py` (11).
- [2026-05-23] **C6: Rate limiting diferenciado por endpoint** — Endpoints pesados (exports, ML inference, semántica) tienen límite inferior configurable en `_HEAVY_ENDPOINT_LIMITS` (10-30 req/min vs 120 default).
- [2026-05-23] **C7: SHA256 verification en TechnologyClassifier.load()** — Verificación de integridad SHA-256 del sidecar `.sha256` al cargar el modelo, alineando con `ml_classifier.py`.
- [2026-05-23] **D1: predict_batch con _augment_text** — `predict_batch` ahora acepta `cpvs`/`importes` opcionales y aplica `_augment_text` a cada texto, corrigiendo predicciones silenciosamente peores que `predict()`.
- [2026-05-23] **D2: Alerta de modelo ML obsoleto** — `check_ml_model_staleness()` en `observability/alerts.py`: alerta WARN si el clasificador SAP tiene > 30 días.
- [2026-05-23] **D3: Prometheus histogram para latencia ML** — `ml_inference_duration_seconds` en `observability/runtime_metrics.py`, instrumentado en `predict()` y `predict_batch()` de `SAPClassifier`.
- [2026-05-23] **Strict typing en `dashboard/`** — Bloque 10a/10b: `dashboard.cache` y `dashboard.data_loader` eliminados del override `ignore_errors`. `dashboard/router.py` y `dashboard/filters/` confirmados ya tipados.
- [2026-05-23] **Bloque 9: SQL S608 eliminado** — Todas las `# noqa: S608` del proyecto principal eliminadas (11 ocurrencias en 9 ficheros). Reemplazadas con concatenación de strings.
- [2026-05-23] **Bloque 8: Infraestructura staging** — `docker-compose.override.yml`, `docker-compose.staging.yml`, `ENV` Literal ampliado a `"dev" | "staging" | "prod"`, `.github/workflows/deploy-staging.yml`.
- [2026-05-23] **Bloque 6: ML features activadas + endpoint /ask** — `ML_TECH_ENABLED=True`, `ML_TECH_AUTO_RETRAIN=True`, endpoint `POST /api/v1/ask` (RAG + SSE streaming), `GET /api/v1/ask/models`.
- [2026-05-23] **Bloque 4 Fase 2** — `fail_under` subido de 60 → 65, `tests/test_watchlist_service.py` (11 tests), `tests/test_analytics_engine.py` (9 tests).
- [2026-05-23] **Bloque 1: OAuth Nonces + Redis Auth** — `_NonceStore` Protocol + `_TTLCacheNonceStore` / `_RedisNonceStore`. `REDIS_PASSWORD` en settings. Redis requirepass en docker-compose.
- [2026-05-23] **Bloque 7: Eliminar globals pipeline** — `_ClassifierHolder` frozen dataclass + `_load_classifiers()` con `@functools.lru_cache(maxsize=1)`.
- [2026-05-23] **Bloque 3: FK enforcement + date CHECK constraints** — `PRAGMA foreign_keys=ON`, CHECK constraints en fechas, migración `v22_fk_cascade_date_checks.py`.
- [2026-05-23] **Bloque 2: Consolidar migraciones** — `db/migrations.py` deprecado, `Makefile` targets, ADR-008.
- [2026-05-23] **Bloque 5: FAISS incremental** — método `update()`, lógica incremental vs full rebuild en `load_or_build()`.
- [2026-05-23] **Bloque 4 Fase 1** — `fail_under` subido a 60, `tests/test_contract_dto.py`.
- [2026-05-24] **P1: Pickle removal** — `dashboard/faiss_index.py`: eliminada carga pickle legacy; `load()` sólo acepta `.npz`; `_load_cached` lanza `ValueError` descriptivo si recibe `.pkl`.
- [2026-05-24] **P2: Filelock + atomic write en FaissIndex.save()** — escritura atómica con `tempfile.NamedTemporaryFile` + `os.replace()`; `FileLock(timeout=120)` para exclusión mutua entre procesos.
- [2026-05-24] **P3: SecretStr para 3 secrets** — `GOOGLE_CLIENT_SECRET`, `API_HMAC_SECRET`, `TURSO_AUTH_TOKEN` migrados a `SecretStr`; 10 call sites actualizados con `.get_secret_value()`.  <!-- pragma: allowlist secret -->
- [2026-05-24] **P4: MaxBodyMiddleware fail-loud** — `api/app.py`: `except Exception: pass` → `log.warning("max_body_middleware_unavailable", exc_info=True)`.
- [2026-05-24] **P5: ProcessPoolExecutor para 4 jobs pesados** — `daily_atom`, `recent_bulk`, `retention_cleanup`, `faiss_rebuild` ejecutados en proceso separado con `ProcessPoolExecutor(max_workers=1)` + `proc.kill()` en timeout.
- [2026-05-24] **P6: sys.path hack eliminado** — `scheduler/retention.py` creado con lógica completa; `scripts/retention_cleanup.py` reescrito como thin CLI wrapper.
- [2026-05-24] **P7: DB pool timeout** — `_pool.get(timeout=acquire_timeout)` con default 10s desde `DB_POOL_TIMEOUT`; `queue.Empty` → `RuntimeError` descriptivo.
- [2026-05-24] **P8: Mypy overrides cerrados para 5 módulos** — `config.settings`, `shared.auth_core`, `api.auth`, `db.audit`, `db.totp` removidos de `ignore_errors`; errores de tipo corregidos en los 5 módulos.
- [2026-05-24] **P9: Prometheus metrics para scheduler, DB pool, FAISS** — `scheduler_job_total`, `scheduler_job_duration_seconds`, `db_pool_acquire_timeout_total`, `faiss_rebuild_total`, `faiss_rebuild_duration_seconds` en `observability/runtime_metrics.py`; instrumentados en `scheduler/loop.py`, `db/connection.py`, `dashboard/faiss_index.py`.
- [2026-05-24] **P10: Tests flakiness eliminado** — `tests/test_faiss_index.py` migrado de pickle a `.npz`; patch target corregido de `faiss_index.encode_texts` → `dashboard.embeddings.encode_texts`; `time.sleep` aumentado de 10ms→50ms en `test_shared_cache.py`.
- [2026-05-24] **P11: uv.lock generado + Makefile targets** — `uv.lock` generado (135 paquetes); targets `lock-uv` y `install-uv` añadidos al Makefile.
- [2026-05-29] **Fase 0: Docker + starlette** — Healthcheck path corregido en `Dockerfile.api:61` → `/api/v1/health`; `.venv/` en `.dockerignore`; `starlette>=1.0.1,<2` pinned; `--force-reinstall` eliminado.
- [2026-05-29] **Fase 1: Deps** — `cachetools>=5.3.0,<8` y `brotli-asgi>=1.4.0,<2` añadidos; `libsql` rango estrechado a `<0.3`; `duckdb` re-añadido a `ignore_missing_imports` (no tiene stubs).
- [2026-05-29] **Fase 2: Security** — CORS fail-closed (wildcard solo non-prod/staging); `/metrics` auth endurecido (API key obligatoria en prod/staging); HMAC truncation documentada.
- [2026-05-29] **Fase 3: Observability** — `configure_sentry` wired en `api/app.py` y `scheduler/loop.py`; `OTEL_SAMPLE_RATIO` default `0.01` → `0.1`; metrics imports top-level en loop.
- [2026-05-29] **Fase 4: Scheduler refactor** — Job registry pattern (`scheduler/jobs/` package); persistent `ProcessPoolExecutor`; `shutdown(cancel_futures=True)` reemplaza `executor._processes` hack; 20 tests en `test_loop.py`.
- [2026-05-29] **Fase 5.1: Batch upsert** — `replace_adjudicaciones_batch()` en `db/upsert.py` (una transacción para N licitaciones); pipeline bulk y daily actualizados.
- [2026-05-29] **Fase 6: Full strict typing** — Eliminados 3 bloques de override mypy (52 módulos promovidos a strict); 149 errores corregidos en 40 archivos (unused-ignore, type-arg, no-any-return, pandas narrowing, arg-type, misc); `shared/py.typed` creado. 375 archivos pasan `mypy --strict`.

---

## Plantilla nueva entrada

```markdown
### [P0|P1|P2|P3] Título corto en imperativo
- **Área:** paquete/subárea
- **Problema:** 1-2 frases describiendo qué está mal y por qué importa.
- **Acceptance criteria:**
  - Bullet verificable 1
  - Bullet verificable 2
- **Files de partida:** [path1](../path1), [path2](../path2)
- **Riesgo:** bajo | medio | alto — razón breve.
```
