---
rfc: pendiente
title: "UX · Grafos Red Órgano-Empresa y Ecosistema Partners — rehacer la capa de visualización (ForceGraph) y cerrar el drill-down"
issue: pendiente (crear issue y renumerar)
author: agent:architect
date: 2026-06-28
status: implemented
area: web/red-organo-empresa · web/ecosistema-partners · web/components/charts/force-graph
supersedes: >
  Completa el trabajo diferido en docs/rfc/2026-06-16-rfc-ux-red-organo-empresa.md
  y docs/rfc/2026-06-16-rfc-ux-ecosistema-partners.md (ambos `implemented`: arreglaron
  los DATOS — aristas reales — pero dejaron explícitamente fuera el componente
  `ForceGraph` y difirieron el drill-down nodo/arista).
---

## Contexto

Dos páginas dibujan grafos de red y comparten el mismo componente
[`web/src/components/charts/force-graph.tsx`](../../web/src/components/charts/force-graph.tsx):

- [`red-organo-empresa/page.tsx`](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx) — grafo **bipartito** órgano↔empresa.
- [`ecosistema-partners/page.tsx`](../../web/src/app/(dashboard)/ecosistema-partners/page.tsx) — grafo **empresa↔empresa** de co-licitación (UTE).

Los dos RFCs de junio (`ux-red-organo-empresa`, `ux-ecosistema-partners`) ya
arreglaron lo importante a nivel de **datos**: las aristas son reales
(adjudicaciones / UTEs), acotadas y filtradas en backend. Pero **ambos dijeron
literalmente "No se rehace el componente `ForceGraph`"** y ambos dejaron
**diferido el drill-down** (click en nodo/arista → detalle). El resultado es que
los datos son correctos pero **el grafo se ve mal y no es accionable** — que es
justo la queja.

### Defectos concretos de la capa de render (no de los datos)

1. **Leyenda con colores que no coinciden con los nodos.** El grafo colorea por
   grupo con `scaleOrdinal(schemeTableau10)` keyed por orden de aparición
   ([force-graph.tsx:107,153](../../web/src/components/charts/force-graph.tsx)). En la
   red bipartita los nodos vienen órganos-primero, así que `organo`→`#4e79a7`
   (azul) y `empresa`→`#f28e2b` (naranja). Pero la leyenda de la página
   **hardcodea** `empresa = #e15759` (rojo)
   ([red-organo-empresa/page.tsx:216](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx)).
   La leyenda miente sobre lo que se ve. Además viola §3 (sin hardcode de algo
   que debe derivar del dato/escala).
2. **El resaltado por búsqueda está muerto.** `ecosistema-partners` calcula
   `_highlighted` por nodo
   ([page.tsx:116](../../web/src/app/(dashboard)/ecosistema-partners/page.tsx)) pero
   `ForceGraph` **no conoce ese campo** (no está en su interfaz `GraphNode` ni se
   pinta). Buscar un partner no resalta nada en el grafo.
3. **Componentes inconexos se escapan del lienzo.** Solo hay `forceCenter`
   (centra el centroide) + `forceManyBody(-120)`, sin fuerza de contención
   (`forceX/forceY`) ni clamp a bounding box
   ([force-graph.tsx:109-118](../../web/src/components/charts/force-graph.tsx)). Los
   subgrafos desconectados (típicos aquí: muchas díadas órgano-empresa o
   UTEs aisladas) salen volando fuera del SVG → "grafo vacío" aparente.
4. **Sin zoom-to-fit inicial.** Hay zoom manual pero ningún `fit` automático: el
   grafo nace descentrado/mal escalado y el usuario tiene que pelearse con el pan/zoom.
5. **Aristas planas e ilegibles.** El peso se **clampa a 8 en el cliente**
   (`Math.min(e.contratos, 8)`,
   [red-organo-empresa/page.tsx:90](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx),
   [ecosistema-partners/page.tsx:121](../../web/src/app/(dashboard)/ecosistema-partners/page.tsx)),
   el `stroke` es `--border` (casi invisible) y no hay escala de grosor ni opacidad
   por peso ([force-graph.tsx:144-145](../../web/src/components/charts/force-graph.tsx)).
   Relaciones fuertes y débiles se ven igual.
6. **Tooltip pobre.** Solo muestra `label` + `group`
   ([force-graph.tsx:162](../../web/src/components/charts/force-graph.tsx)); ni importe,
   ni nº de contratos, ni grado — métricas que el backend ya entrega por nodo.
7. **Re-layout en cada resize.** El `useEffect` depende de `size`, y un
   `ResizeObserver` actualiza `size` ([force-graph.tsx:63-78,214](../../web/src/components/charts/force-graph.tsx)):
   cualquier cambio de ancho **reinicia la simulación** y el grafo "explota" y
   se reordena.
8. **Etiquetas arbitrarias y solapadas.** Solo etiqueta nodos con
   `radius >= sizeScale(median)` ([force-graph.tsx:190](../../web/src/components/charts/force-graph.tsx)),
   sin anti-solape: nodos importantes quedan sin nombre y los visibles se pisan.
9. **Sin estructura para el bipartito.** Un force layout libre no comunica la
   naturaleza órgano|empresa; un layout bipartito (dos columnas) lo haría legible
   de un vistazo.
10. **Sin comunidades en partners.** Todos los nodos de `ecosistema-partners` son
    grupo `"empresa"` → todos del mismo color. El insight real ("¿qué clústeres de
    empresas co-licitan juntas?") no se ve porque no hay detección de comunidades
    ni coloreo por clúster.
11. **Drill-down inexistente.** `ForceGraph` expone `onNodeClick` pero ninguna de
    las dos páginas lo cablea: click en un nodo no lleva a `/detalle` ni a las
    licitaciones que sostienen la arista (diferido en ambos RFCs).

## Decisión

Rehacer la **capa de visualización de red** (el ítem que ambos RFCs aparcaron),
con pequeñas extensiones de backend que la alimenten. La corrección de datos NO
se toca (ya está bien); esto es puramente render + interacción + una señal de
clustering nueva.

### A. Reescribir `ForceGraph` → `NetworkGraph`

Nuevo componente (o reescritura in-place con API compatible) con:

1. **Layout consciente del tipo.** Prop `layout: "force" | "bipartite"`.
   - `bipartite` (red órgano-empresa): órganos en una columna, empresas en otra,
     con `forceX` por tipo + `forceY` de reparto; aristas legibles izquierda→derecha.
   - `force` (partners): force layout con contención (`forceX/forceY` suaves hacia
     el centro) para que nada se escape del lienzo.
2. **Zoom-to-fit automático** tras estabilizar (`on("end")` o tras N ticks):
   calcula el bounding box de los nodos y aplica el `transform` que encuadra todo
   con padding. Botón "Encuadrar" para re-fit manual.
3. **Aristas con significado.** Grosor por escala (`scaleLinear`/`scaleSqrt` sobre
   el peso real, sin clamp en cliente) y opacidad por peso; resaltado de la arista
   en hover con su métrica.
4. **Resaltado de vecindario.** Hover/click sobre un nodo atenúa (opacidad baja)
   todo lo no adyacente y resalta el nodo + sus aristas + vecinos. Implementa de
   verdad el `highlighted` por búsqueda (prop `highlightIds: string[]`).
5. **Tooltip rico.** Nombre + tipo + importe + nº contratos + grado (las métricas
   que ya vienen del backend por nodo). Para aristas: origen→destino + contratos +
   importe.
6. **Leyenda dirigida por datos.** La leyenda recibe el mapa `grupo→color` REAL
   usado por la escala (no colores hardcodeados). Una sola fuente de verdad de color.
7. **Coloreo por comunidad** (partners): si el nodo trae `community`, colorea por
   clúster con una paleta categórica estable; leyenda "Clúster 1..n".
8. **Etiquetas decluttered.** Mostrar etiqueta de los top-K por tamaño + del nodo
   en hover/selección; evitar solape (descartar etiquetas que colisionan).
9. **Estabilidad ante resize.** Separar "construir simulación" (depende de
   datos/layout) de "redimensionar viewport" (solo reescala/reencuadra, sin
   reiniciar la simulación). `prefers-reduced-motion` → layout estático ya
   encuadrado (se conserva el soporte actual).
10. **Drill-down.** `onNodeClick` → `/detalle?...` (órgano/empresa) y, en
    bipartito, click en arista → listado de las licitaciones que la sustentan
    (navegación con filtro). Cablear en ambas páginas.
11. **Accesibilidad/mobile.** Foco por teclado en nodos con tooltip accesible;
    controles (sliders) usables en móvil; altura responsive.

### B. Backend: señal de clustering para partners (aditivo)

Extender [`services/partners.py::build_partnership_graph`](../../services/partners.py) /
[`services/analytics/ecosistema_partners.py`](../../services/analytics/ecosistema_partners.py)
para añadir a cada `PartnerNode` un campo opcional **`community: int | None`** vía
detección de comunidades por modularidad (greedy / Louvain sobre el grafo de
co-licitación). Es la única síntesis nueva y va en **backend** (§3.8: el frontend
no inventa clústeres). Para el bipartito, el backend ya entrega `type`, `degree` e
`importe_total` por nodo (suficiente para tamaño/leyenda); no requiere cambio salvo,
opcionalmente, exponer `degree` ya presente.

### C. Qué NO se hace

- **No** se cambia el origen ni el significado de las aristas (siguen siendo
  adjudicaciones / UTEs reales del backend).
- **No** se migra a una librería pesada de grafos si d3-force basta; se permite
  evaluar una lib canvas (ver alternativas) solo si el nº de nodos lo exige.
- **No** se sube el top-N por defecto para "llenar" el grafo: legibilidad > densidad.
- **No** se fabrica nada en cliente: comunidades y métricas vienen del backend.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Grafo ilegible, leyenda falsa, búsqueda muerta, sin drill-down | Es exactamente la queja |
| Parches mínimos (arreglar leyenda + clamp aristas) | Rápido | No resuelve fly-away, fit, vecindario, comunidades, drill-down | Insuficiente |
| Reescribir `ForceGraph` con d3-force (elegida) | Control total, sin dependencias nuevas, reusa la base | Hay que escribir layout/fit/interacción | — |
| Migrar a `react-force-graph` / `sigma.js` (canvas/WebGL) | Escala a miles de nodos, físicas listas | Dependencia grande; los grafos aquí son top-N (decenas) | Sobredimensionado; mantener como opción si crece |
| Renderizar comunidades en cliente | Sin backend | Viola §3.8 (síntesis analítica en front) | Anti-patrón |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `PartnerNode.community` nuevo; props de `NetworkGraph` tipadas | Tipar; regenerar `@/generated/api` |
| §3.5 Pydantic v2 DTOs | **Aditivo**: `community: int \| None` en `PartnerNode` | Campo opcional, backward-compatible |
| §3.8 Frontend vía API / ADR-014 | **Refuerza**: comunidades y color-map salen del backend/escala, no del front; se elimina el color hardcodeado de la leyenda | `check_frontend_invariants.py` (synthetic-graph sigue 0) |
| §3.3 Migraciones | Ninguno (no hay esquema nuevo; se calcula al vuelo) | — |
| §3.2 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. **Backend** — `services/partners.py`: calcular `community` por modularidad
   (networkx greedy/Louvain) sobre el grafo de co-licitación; propagar en
   `services/analytics/ecosistema_partners.py` (`PartnerNode.community`). Sin
   romper la firma; comunidad `None` si el grafo es trivial.
2. **Componente** — reescribir `force-graph.tsx` como `NetworkGraph` con: prop
   `layout`, zoom-to-fit, contención, escala de aristas, resaltado de vecindario,
   `highlightIds`, tooltip rico, leyenda dirigida por datos, coloreo por comunidad,
   etiquetas decluttered, estabilidad ante resize, `onNodeClick`/`onLinkClick`,
   a11y/mobile. Mantener `prefers-reduced-motion`.
3. **`red-organo-empresa/page.tsx`** — usar `layout="bipartite"`; pasar métricas
   por nodo al tooltip; leyenda dirigida por datos (sin `#e15759` hardcode);
   cablear `onNodeClick`→`/detalle` y `onLinkClick`→listado.
4. **`ecosistema-partners/page.tsx`** — `layout="force"`; pasar `community` al
   color; `highlightIds` desde la búsqueda (revivir el resaltado); drill-down nodo
   →perfil de empresa.
5. **Regenerar `@/generated/api`** (campo `community`).
6. **Tests**
   - Backend: `community` se asigna y es estable; grafo trivial → `None`;
     no rompe min_contratos/top_nodes.
   - Componente (vitest + testing-library): la leyenda refleja los colores reales;
     `highlightIds` resalta; `onNodeClick`/`onLinkClick` disparan; reduced-motion
     no corre simulación; sin nodos fuera del viewBox tras fit.
   - Páginas: click en nodo navega a `/detalle`.

**Archivos de partida**:
- [`web/src/components/charts/force-graph.tsx`](../../web/src/components/charts/force-graph.tsx) (reescritura)
- [`web/src/app/(dashboard)/red-organo-empresa/page.tsx`](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx:80) (graphNodes/links, leyenda, drill-down)
- [`web/src/app/(dashboard)/ecosistema-partners/page.tsx`](../../web/src/app/(dashboard)/ecosistema-partners/page.tsx:109) (graph, `_highlighted`, drill-down)
- [`services/partners.py`](../../services/partners.py:19) (`build_partnership_graph` + community)
- [`services/analytics/ecosistema_partners.py`](../../services/analytics/ecosistema_partners.py) (`PartnerNode.community`)
- RFCs previos: `2026-06-16-rfc-ux-red-organo-empresa.md`, `2026-06-16-rfc-ux-ecosistema-partners.md`

**Riesgo estimado**: medio (el grueso es frontend d3; el backend de comunidades es
acotado y aditivo).
**Tiempo estimado**: 2-3 días.

## Acceptance criteria

- [ ] La leyenda muestra exactamente los colores que se renderizan (un único
      `grupo→color` derivado de la escala; sin colores hardcodeados).
- [ ] Ningún nodo queda fuera del viewport tras el encuadre automático; existe
      botón "Encuadrar".
- [ ] El grosor/opacidad de la arista refleja su peso real (sin clamp a 8 en cliente).
- [ ] Hover/click sobre un nodo resalta su vecindario y atenúa el resto; la
      búsqueda en `ecosistema-partners` resalta nodos (`highlightIds` funciona).
- [ ] El tooltip muestra importe, nº contratos y grado por nodo.
- [ ] `ecosistema-partners` colorea por comunidad (campo `community` del backend);
      la red bipartita usa `layout="bipartite"` legible órgano|empresa.
- [ ] Click en nodo → `/detalle`; click en arista (bipartito) → listado de
      licitaciones que la sustentan.
- [ ] Redimensionar la ventana no reinicia/explota la simulación.
- [ ] `python scripts/check_frontend_invariants.py` mantiene `synthetic-graph` en 0.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make lint && make typecheck && make test-unit` (backend) en verde.
- [ ] diff-cover ≥ 80 % en líneas nuevas.

## Notas de review

<!-- 2026-06-28T00:00Z agent:architect — borrador inicial -->

**2026-06-28 — Implementado.**

- **Backend:** `services/partners.py` calcula `community` por modularidad
  (`networkx.community.louvain_communities`, `seed=42`, determinista; `None` si el
  grafo es trivial ≤1 clúster o <3 nodos); propagado en `PartnerNode.community`
  (`services/analytics/ecosistema_partners.py`). Override de mypy para `networkx`
  en `pyproject.toml`. Tests: `tests/test_partners.py` (campo presente + detección
  de 2 clústeres desconectados).
- **Componente:** reescrito `web/src/components/charts/force-graph.tsx`
  (export `ForceGraph` conservado). Espacio de coordenadas virtual + `viewBox`
  auto-fit → **resize ya no reinicia la simulación** (causa raíz del "explota al
  redimensionar). Props nuevas: `layout` (`force`/`bipartite`), `highlightIds`,
  `groupLabels`, `onNodeClick`, `onLinkClick`. Fuerzas de contención
  (`forceX/forceY`) → los componentes inconexos no se escapan. Encuadre automático
  + botón "Encuadrar". Aristas con grosor por escala real (sin clamp). Tooltip rico
  (importe/contratos/conexiones). **Leyenda dirigida por datos** (misma escala
  `scaleOrdinal` que los nodos → fin del desajuste leyenda↔nodo y del color
  hardcodeado). Resaltado de vecindario en hover + `highlightIds` (revive la
  búsqueda muerta). Coloreo por comunidad. Etiquetas decluttered. `reduced-motion`
  → layout estático encuadrado.
- **Páginas:** `red-organo-empresa` usa `layout="bipartite"`, leyenda por datos
  (eliminado `#4e79a7`/`#e15759` hardcodeado), drill-down nodo→`/organos|empresas?q=`
  y arista→empresa. `ecosistema-partners` colorea por `community`, `highlightIds`
  desde la búsqueda, drill-down nodo→`/empresas?q=`. Deep-link `?q=` añadido a
  `organos` y `empresas` (init perezoso, sin `setState`-en-effect).
- **Tests:** `web/src/components/charts/__tests__/force-graph.test.tsx` (4):
  leyenda↔nodo mismo color, drill-down, `highlightIds` atenúa no-resaltados.
- **Verde:** `tsc`/`eslint` (web), `vitest` (4 nuevos + 280; 1 fallo preexistente
  ajeno: `search-history.test.ts` → `localStorage.clear` del entorno),
  `pytest`/`ruff`/`mypy` (backend, 20 tests analytics).
  `check_frontend_invariants`: 0 hallazgos nuevos (`synthetic-graph` sigue 0).
- **Diferido:** arista bipartita → *listado de licitaciones que la sustentan*
  (no existe ruta filtrada órgano×empresa; hoy la arista lleva a la empresa
  adjudicataria). Posible migración futura a canvas/WebGL solo si el nº de nodos crece.
