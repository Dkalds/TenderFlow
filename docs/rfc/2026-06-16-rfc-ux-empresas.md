---
rfc: pendiente
title: "UX/KPIs · Empresas — perfil con posicionamiento competitivo, trend temporal y drill-down"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/empresas
---

## Contexto

`web/src/app/(dashboard)/empresas/page.tsx` es una página muy sólida: maestro de
empresas canónicas con KPIs de cobertura (empresas, % importe resuelto, vigiladas,
revisiones pendientes), buscador, tabla con toggle de vigilancia, perfil de empresa
(totales, desgloses por CPV/CCAA/órgano, UTEs, aliases) y una cola de revisión de
matches fuzzy con aceptar/rechazar. El manejo de mutaciones e invalidación es
correcto.

El gap no es de calidad de implementación sino de **valor analítico**: el perfil es
**descriptivo**, no **comparativo**, en un producto cuyo diferencial es la
inteligencia competitiva. Concretamente:

1. **Sin posicionamiento competitivo.** El perfil muestra contratos, importe y
   "ofertas medias (presión)", pero no **cuota de mercado** dentro de su CPV/CCAA,
   ni **ranking entre pares**, ni win-rate. Un usuario no sabe si la empresa es
   líder o marginal en su nicho — que es la pregunta de negocio.
2. **Sin trayectoria temporal.** Se muestran `primera_adjudicacion`/
   `ultima_adjudicacion` (líneas 323-324), pero no un gráfico de actividad en el
   tiempo: no se ve si la empresa está creciendo o declinando, señal competitiva
   clave.
3. **Sin puente a los contratos.** Los desgloses (`MiniRanking`) no enlazan a las
   adjudicaciones/licitaciones reales de la empresa; el análisis no aterriza en los
   registros.
4. **Lista con límite duro de 50, sin paginación** (`/api/v1/empresas?limit=50`,
   línea 120): el maestro puede tener más; no hay "cargar más".

> El perfil ya consume `/api/v1/competitive/empresas/{id}/perfil`. Las nuevas KPIs
> competitivas se calculan en `services/competitive/` y se exponen por API (§3.8);
> contrato aditivo (§3.5).

## Decisión

Enriquecer el perfil de empresa con **inteligencia competitiva**, reutilizando el
endpoint de perfil y añadiendo solo los campos que falten.

1. **KPIs de posicionamiento.** Por cada CPV/CCAA donde la empresa opera: su
   **cuota** (importe de la empresa / importe total del nicho) y su **rank** entre
   competidores. Card resumen "líder en N nichos / top-3 en M". Win-rate si el dato
   de ofertas lo permite.
2. **Trend temporal.** Mini gráfico de contratos/importe por año (o trimestre) en
   el perfil, marcando tendencia (↑/↓). Fuente: agregación temporal de las
   adjudicaciones de la empresa.
3. **Drill-down a contratos.** Cada fila de `MiniRanking` (CPV/CCAA/órgano) y un
   botón "ver adjudicaciones" enlazan al listado filtrado por empresa (+ ese
   CPV/CCAA/órgano).
4. **Paginación del maestro.** "Cargar más" o paginación en la tabla de empresas,
   en vez del corte fijo a 50.

**Qué NO se hace:**

- **No** se rehace el resolutor de entidades ni la cola de revisión (ya correctos).
- **No** se aplican los filtros globales al maestro (es entidad, no vista filtrada);
  el filtrado vive dentro del perfil/contratos.
- **No** se añade scraping de datos externos de empresa (RM, financieros): fuera de
  scope; solo lo derivable de adjudicaciones.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Perfil descriptivo, no responde "¿es líder?" | No explota el diferencial competitivo |
| Calcular cuota/rank en el cliente | Sin backend | Necesita el universo del nicho (no está en el cliente); pesado | El backend tiene el dato |
| Perfil con posicionamiento + trend + drill-down (elegida) | Convierte el maestro en inteligencia accionable | Campos DTO nuevos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados nuevos (cuota, rank, serie temporal) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo** en el perfil competitivo | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | Cuota/rank/trend se calculan en `services/competitive/` | Endpoint dedicado |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/competitive/` + `api/routes/competitive.py` — extender el perfil con
   cuota/rank por nicho, serie temporal y (si procede) win-rate.
2. `empresas/page.tsx` (`EmpresaPerfil`) — cards de posicionamiento, mini-chart de
   trend, `MiniRanking` con enlace, botón "ver adjudicaciones".
3. Paginación en la tabla del maestro.
4. Regenerar `@/generated/api`.
5. Tests vitest: posicionamiento renderiza cuota/rank; drill-down navega filtrado;
   paginación carga páginas siguientes.

**Archivos de partida**: `empresas/page.tsx:104-290,296-441`,
`services/competitive/` (perfil), `api/routes/competitive.py`,
`api/routes/empresas.py`.
**Riesgo estimado**: medio — añade cálculo competitivo en backend (cuota/rank por
nicho) que conviene cachear.
**Tiempo estimado**: 1.5-2 días.

## Acceptance criteria

- [ ] El perfil muestra cuota de mercado y rank de la empresa en sus nichos CPV/CCAA.
- [ ] El perfil incluye un trend temporal de actividad (↑/↓).
- [ ] Los desgloses y un botón enlazan a las adjudicaciones reales de la empresa.
- [ ] La tabla del maestro pagina más allá de 50.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-25 — **Implementado (criterio #2: trayectoria temporal).** El perfil
mostraba `primera`/`ultima_adjudicacion` pero no la evolución: no se veía si la
empresa crece o decae (señal competitiva clave). Backend
(`services/competitive/mercado.py::perfil_empresa`): nuevo `por_anio` — serie
cronológica `(anio, contratos, importe)` por empresa (`GROUP BY` año de
`fecha_adjudicacion`, `HAVING anio IS NOT NULL`). Como el endpoint
`/competitive/empresas/{id}/perfil` lo comparten Empresas y Competidores, ambos
se benefician. Frontend (`empresas/page.tsx`): componente `YearTrend` — barras por
año en orden cronológico y un badge de tendencia (↑/↓/→ con el delta vs el año
anterior). Sin librería de charts nueva (barras inline). Test backend
`test_perfil_empresa_por_anio_traza_la_trayectoria` (2023→2024 al alza, orden y
sin años nulos). Verde: pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285).

**Diferido:** KPIs de posicionamiento (cuota de mercado y rank por nicho CPV/CCAA,
#1) — requieren cómputo del universo del nicho en backend; drill-down de los
desgloses a las adjudicaciones reales (#3); y paginación del maestro más allá de
50 (#4).
