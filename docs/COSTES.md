# Coste de la plataforma

**Última revisión: 2026-09-06.** Se revisa cada mes junto a
[docs/sli-slo.md](sli-slo.md). Un coste sin fecha de medición no es un coste, es
un recuerdo.

Este documento existe porque hasta hoy no había ninguno: el backlog descartaba
staging «por coste» sin que nadie pudiera decir cuánto costaba lo que ya hay
(hecho 17 del plan complementario 2026-09).

---

## 1. Cómo leer esta tabla

- **Declarado** sale de la configuración commiteada (`render.yaml`,
  `config/settings.py`, los workflows). Es reproducible: el comando de la
  columna lo vuelve a sacar.
- **Facturado** sale del panel del proveedor y lo rellena el mantenedor. Nadie
  puede derivarlo del repositorio, así que se anota a mano **con fecha**.
- Un valor **por medir** es un valor que nadie ha mirado todavía. No se
  sustituye por una estimación: una cifra inventada es peor que un hueco.

---

## 2. Render — cómputo y observabilidad

| Servicio | Tipo | Plan declarado | Disco | Dónde se declara |
|---|---|---|---|---|
| `tenderflow-api` | `web` | `standard`, región `frankfurt` | — | `render.yaml` |
| `tenderflow-prometheus` | `pserv` | `starter`, `frankfurt` | 10 GB | `render.yaml` |
| `tenderflow-alertmanager` | `pserv` | `starter`, `frankfurt` | 1 GB | `render.yaml` |
| `tenderflow-grafana` | `web` | `starter`, `frankfurt` | 1 GB | `render.yaml` |
| `tenderflow-mcp` | `web` | `starter`, `frankfurt` — alta a mano | — | `render.yaml` |

```bash
grep -n "name:\|type:\|plan:\|sizeGB:" render.yaml
```

**Facturado mensual: por medir** (panel de Render → Billing).

**Pendientes de coste conocido en este plan:**

- El servicio `worker` de [ADR-028](adr/ADR-028-cola-de-trabajo-y-worker.md)
  está declarado en `render.yaml` pero **no existe todavía en Render**: se crea
  en el paso 1 del [runbook del cutover del cron](runbooks/cutover-cron-al-worker.md).
  Declarado en `standard` (2 GB) y no en `starter` porque, con el plano de cron
  de [ADR-033](adr/ADR-033-plano-de-cron-en-el-worker.md), corre el scoring y la
  ingesta diaria en el mismo proceso que la cola; el motivo y cuándo
  revisarlo están junto al servicio en `render.yaml`. Su facturado se anota
  aquí tras el primer mes.
- El preview por PR de C3.5 es efímero: su coste es proporcional a las PR
  abiertas y se anota tras el primer mes de uso real, no antes.

---

## 3. Supabase — Postgres

| Concepto | Declarado | Comando |
|---|---|---|
| Instancia | fuera del repositorio (`DATABASE_URL`) | `make check-env-parity` |
| Tamaño de la BD | por medir | `SELECT pg_size_pretty(pg_database_size(current_database()))` |
| Almacén de objetos ([ADR-029](adr/ADR-029-almacen-de-objetos.md)) | aún no provisionado | `/analytics/quality` cuando exista |

**Facturado mensual: por medir.**

La retención es lo que mantiene esta cifra acotada, y está publicada en
[SECURITY.md](SECURITY.md#retención-de-datos): sin plazos, el coste de Postgres
crece de forma monótona por construcción.

---

## 4. Vercel — frontend

| Concepto | Declarado | Comando |
|---|---|---|
| Proyecto | fuera del repositorio | — |
| Presupuesto de bundle | umbrales por ruta versionados (C7.6) | job `bundle-budget` en `ci.yml` |

**Facturado mensual: por medir.**

---

## 5. LLM

A diferencia de los anteriores, este coste **sí está acotado en código** y el
tope es exigible en tiempo de ejecución:

| Variable | Valor por defecto | Qué acota |
|---|---|---|
| `LLM_BUDGET_USD_DAILY` | 5,00 | Gasto diario de toda la plataforma |
| `LLM_BUDGET_USD_MONTHLY` | 50,00 | Gasto mensual de toda la plataforma |
| `LLM_BUDGET_USD_DAILY_PER_USER` | 1,00 | Gasto diario por usuario |
| `LLM_BUDGET_USD_DAILY_PER_ORG` | ver `.env.example` | Gasto diario por organización (C2.9) |
| `LLM_BUDGET_MODE` | `enforce` | `monitor` solo cuenta; `enforce` devuelve 429 |

```bash
make status   # imprime el presupuesto LLM configurado
```

La alerta `LLMBudgetExceeded` ya existe en
`observability/alert_rules.yml`. Es el único coste de esta página que avisa
solo.

### 5.1 Ficha nocturna del pliego (D52 del plan 2026-10)

La fase de fichas de `pliegos.yml` (`scheduler/jobs/documentos_embeddings.py`,
`_run_facts_phase`) hace dos llamadas al LLM por expediente: la ficha general y,
desde `tender-facts-v7`, una más corta solo para los documentos a presentar
(`_extraer_documentos`; no se hace si ninguna página habla de sobres ni de
DEUC). Su gasto mensual es

> **gasto mensual ≈ fichas por noche × noches al mes × coste por ficha**

y cada factor sale de algo que el código ya mide o declara:

| Factor | De dónde sale | Cómo leerlo |
|---|---|---|
| Fichas por noche | Tope: `PLIEGO_FACTS_BATCH` (25) y `PLIEGO_FACTS_MAX_SECONDS` (1800 s), una corrida al día (`cron: "0 9 * * *"`). Real: `counts["procesadas"]` del log del job, o la tabla | `SELECT left(updated_at::text, 10) AS dia, count(*) FROM tender_fact_sheets WHERE updated_at::text >= to_char(now() - interval '30 days', 'YYYY-MM-DD') GROUP BY 1 ORDER BY 1` |
| Coste por ficha | `llm/client.py::_record_usage`: tokens de entrada y salida × `_PRICE_PER_MTOK[modelo]`. Lo mismo alimenta `llm_cost_usd_total` y el acumulador del `BudgetGuard` | Con `REDIS_URL` en `pliegos.yml`: diferencia de la clave `llm:budget:daily:<AAAA-MM-DD>` antes y después de la corrida, dividida entre `procesadas`. Sin Redis el acumulador arranca de cero en cada corrida y no sirve para medir |
| Cota superior por ficha | `services/rag/fact_sheet.py`: `_MAX_CONTEXT_CHARS` (56 000) + la plantilla de extracción (≤ `MAX_INTERNAL_QUESTION_LEN`, 12 000) de entrada, ≤ `_MAX_OUTPUT_TOKENS` (8 000) de salida; más la pasada de documentos, `_DOC_MAX_CONTEXT_CHARS` (32 000) de entrada y ≤ `_DOC_MAX_OUTPUT_TOKENS` (4 000) de salida | Con `nvidia/nemotron-3-ultra-550b-a55b` a su precio **nocional** (0,90 / 3,60 USD por millón): ~20 000 tokens de entrada y 8 000 de salida dan ≤ 0,05 USD; la pasada de documentos (~9 000 y 4 000) suma ≤ 0,025: **≤ 0,075 USD por ficha** |

Medido el 2026-10-26 (MCP de solo lectura): del 2026-09-26 al 2026-10-19 salieron
25 fichas por noche, casi siempre el lote entero; del 20 al 26 de octubre, entre 1
y 17. Con el tope actual son ≤ 750 fichas al mes y, con la cota de arriba,
**≤ 56 USD nocionales al mes** (750 × 0,075; eran 37,5 con una sola llamada,
antes de `tender-facts-v7`). Es una cota: la pasada de documentos rara vez llena
su presupuesto, pero **la cota ya supera los 50 USD de `LLM_BUDGET_USD_MONTHLY`**. NVIDIA no factura el free tier, así que el
**facturado es 0 mientras se use ese modelo**; el nocional cuenta igual contra
`LLM_BUDGET_USD_MONTHLY` (50 USD, compartido con `/ask` y el resto) si
`pliegos.yml` y la API comparten Redis, y en modo `enforce` un lote grande puede
dejar sin presupuesto al asistente ese mes.

Desde el 2026-10-26 el lote ordena oportunidad abierta → favorito → **abierta
con plazo que casa con alguna regla de vigilancia activa** → el resto
(`TenderFactSheetsRepository.list_pending_licitaciones`). Cambia qué fichas se
pagan, no cuántas: el número lo sigue fijando `PLIEGO_FACTS_BATCH`.

| Concepto | Valor |
|---|---|
| Coste por ficha medido (USD, con fecha) | **por medir** tras la primera semana con Redis compartido |
| Gasto mensual medido (USD, con fecha) | **por medir** |
| **Tope mensual acordado para la ficha nocturna** | **por fijar — lo decide el propietario (D52)** |
| Qué se hace al alcanzarlo | **por fijar** (bajar `PLIEGO_FACTS_BATCH`, o `PLIEGO_FACTS_ENABLED=false`) |

---

## 6. GitHub Actions

| Concepto | Declarado | Comando |
|---|---|---|
| Minutos consumidos | por medir | pestaña Actions → Usage |
| Workflows programados | ver el registry | `make job-parity` |

El plano de cron de producción es Actions
([ADR-012](adr/ADR-012-plano-unico-orquestacion.md)), así que estos minutos no
son gasto de CI: son gasto de operación. Conviene mirarlos aparte de los
minutos de PR.

---

## 7. Umbral de alerta

| Ámbito | Umbral | Qué se hace al superarlo |
|---|---|---|
| LLM diario | `LLM_BUDGET_USD_DAILY` | `LLMBudgetExceeded` dispara; las peticiones nuevas reciben 429 con el cubo agotado |
| Total mensual de la plataforma | **por fijar** tras la primera medición | revisión del mantenedor en la revisión mensual |

El umbral total no se fija con una cifra inventada. Se fija en la primera
revisión que tenga las casillas «facturado» rellenas.
