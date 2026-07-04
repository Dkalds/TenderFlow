# Integridad analítica del frontend

> El frontend **no fabrica datos**. El backend es la **única fuente de verdad
> analítica**. Esta es la extensión operativa del invariante **AGENTS.md §3.8**
> (frontend siempre vía API) y queda registrada en **[[ADR-014-integridad-analitica-frontend|ADR-014]]**.

§3.8 dice "consumí la API"; este documento añade: **"y no fabriques la analítica
que la API no te dio"**. Verificado en CI por
[`scripts/check_frontend_invariants.py`](../scripts/check_frontend_invariants.py).

---

## Los 3 invariantes

1. **El frontend no fabrica analítica.** Cross-tabs, grafos, agregados, totales y
   series temporales se calculan en **backend** sobre el dataset completo
   (distinct donde aplique). El frontend renderiza y compone; **nunca** deriva
   granularidad, relaciones ni totales que el endpoint no entregó. Si un valor es
   estimado, la UI lo **etiqueta** como "estimado" o lo oculta — nunca lo presenta
   como real.

2. **El estado de usuario es server-side.** Reglas, alertas, destacados y vistas
   guardadas persisten en servidor; `localStorage` es **solo** caché o migración
   one-shot. Si una feature necesita disparar trabajo server-side (alertas, email),
   su estado no puede vivir solo en el navegador.

3. **Sin hardcode que el backend/entorno deben proveer.** Listas (flags, usuarios),
   URLs (Grafana) y datos vienen de API/config (env o endpoint `/meta`). Prohibido
   `MOCK_*` / `LOCAL_*` / `localhost` en datos renderizados commiteados.

---

## Los 5 anti-patrones (ejemplos reales de este repo)

### 1 — Dato sintético presentado como real *(el más grave)*

El frontend deriva granularidad o relaciones que el backend no entregó, y las
pinta como dato real.

| Página | Qué se fabricaba | Fix |
|---|---|---|
| `tendencias` | heatmap Mes×Estado = producto de marginales (distribución global × mes) | cross-tab real en `services/analytics` |
| `calendario` | conteos diarios = serie **semanal** ÷ 7 + fudge de día laborable | `group_by=day` real |
| `resumen` | "CCAA cubiertas" = `concentracion_top3 × 17` | `distinct_ccaa()` real |
| `red-organo-empresa` | aristas órgano↔empresa = "comparten CCAA" | grafo de adjudicación real (`services/organ_company_graph.py`) |
| `ecosistema-partners` | aristas empresa↔empresa = co-ocurrencia en CCAA | grafo de UTE/co-licitación real (`services/partners.py`) |

### 2 — Agregación cliente sobre sample/lista parcial, etiquetada como total

| Página | Defecto |
|---|---|
| `geografia` | provincias agregadas en cliente desde `licitaciones?limit=500` (sample, ignora filtros) |
| `organos` | "Importe Total"/"Concentración" sumados sobre el **top-50** devuelto |
| `detalle` | score mergeado desde un `scoring?limit=500` disjunto de la página |
| `proyectos-modulos` | importe sumado por fila de módulo → doble conteo multi-módulo |

**Fix:** los **totales** se calculan en backend sobre el dataset completo (distinct
donde aplique); los charts siguen siendo "top-N".

### 3 — Estado de usuario en `localStorage` cuando necesita servidor

| Página | Defecto |
|---|---|
| `mi-watchlist` | reglas + **frecuencia de alerta** en localStorage → las alertas nunca se envían |
| `detalle` | "destacados" en localStorage (watchlist fragmentada) |
| `investigador` | historial en localStorage |

**Fix:** persistencia server-side (reusar `services/watchlist.py` / `saved_filters.py`);
`localStorage` solo como caché/migración.

### 4 — Hardcode que rompe en despliegue o driftea

| Página | Defecto |
|---|---|
| `observabilidad` | `GRAFANA_URL = "http://localhost:3001"` → enlace roto en prod |
| `feature-flags` | `LOCAL_FLAGS` hardcodeado → flags del backend invisibles |
| `administracion` | `MOCK_USERS` → gestión de usuarios falsa |

**Fix:** config en runtime (env / endpoint `/meta`) y backend como fuente; cero
mock/hardcode en datos renderizados.

### 5 — Señales infrautilizadas y falta de drill-down

`renovaciones` no prioriza por `riesgo_cambio`; `tecnologias` no acciona
`sin_clasificar`; varias vistas no enlazan análisis→registros.

**Fix:** priorizar por las señales disponibles; toda vista analítica enlaza a los
registros que la sustentan.

---

## El patrón correcto (referencia)

La página de **Tecnologías** ya lo hace bien — su backend entrega cross-tabs
**reales** (`cross_organo`, `cross_geo`) y el código lo documenta:
*"Real tecnologia x organo heatmap (replaces the previous synthetic matrix)"*.
Es el patrón a replicar: **el backend expone el agregado/cross-tab/grafo real; el
frontend lo renderiza**.

---

## Checklist al añadir/editar una página analítica

- [ ] ¿Esta vista **deriva** analítica en cliente (cross-tab, grafo, total)? Si sí,
      muévelo a backend o justifícalo.
- [ ] ¿Los **totales** son sobre el dataset completo o sobre un sample/top-N?
- [ ] ¿Hay estado de usuario (reglas/alertas/destacados) que deba persistir en
      servidor en vez de `localStorage`?
- [ ] ¿Hay URLs/listas/datos hardcodeados que el backend o el entorno deban proveer?
- [ ] ¿La vista enlaza a los **registros** que la sustentan (drill-down)?
- [ ] `python scripts/check_frontend_invariants.py` no añade hallazgos nuevos
      (o están justificados con `fdi-allow`).

---

## El check de CI

[`scripts/check_frontend_invariants.py`](../scripts/check_frontend_invariants.py)
escanea `web/src/**` y reporta los 5 anti-patrones. Corre en **modo aviso**
(no bloqueante) por defecto; se endurece a **error por categoría** a medida que las
páginas se migran (precedente: el lint progresivo del frontend).

```bash
make check-frontend-invariants            # modo aviso (reporta, exit 0)
python scripts/check_frontend_invariants.py --strict          # falla ante cualquier hallazgo
python scripts/check_frontend_invariants.py --error-category mock-data  # falla solo en una categoría
```

**Allowlist:** añadí `fdi-allow` (o `fdi-allow:categoria`) en un comentario de la
línea, con justificación, para excluir un hallazgo legítimo (p.ej. el fallback SSR
de `lib/api-client.ts`).
