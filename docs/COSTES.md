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

```bash
grep -n "name:\|type:\|plan:\|sizeGB:" render.yaml
```

**Facturado mensual: por medir** (panel de Render → Billing).

**Pendientes de coste conocido en este plan:**

- El servicio `worker` de [ADR-028](adr/ADR-028-cola-de-trabajo-y-worker.md)
  (v2 S5.3) añade un servicio más. Su plan y su coste se anotan aquí en el
  mismo cambio que lo declare en `render.yaml`.
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
