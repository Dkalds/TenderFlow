# Auditoría UX/UI del frontend

Revisión crítica de `web/` (Next.js 16, App Router) hecha el 2026-08-01, repasada
el 2026-08-27. Prioriza por daño al usuario, no por esfuerzo. La **Ola 1** ya está
implementada; el resto está priorizado abajo y replicado en
[IMPROVEMENT_BACKLOG.md](IMPROVEMENT_BACKLOG.md).

**Tamaño, medido el 2026-08-27:** 43 `page.tsx` y **57.438 líneas** de TS/TSX en
`web/src` excluyendo `src/generated/api.d.ts` (14.109 líneas más, generadas por
codegen: contarlas infla el número sin que nadie las escriba). El árbol de
navegación son **14 espacios de consola** (`lib/console-spaces.ts`), que absorben
como `?vista=` las rutas heredadas.

> Este documento ha citado tres juegos de cifras distintos —"28 rutas / ~27k LOC",
> luego "33 rutas / ~44,7k"— sin decir nunca qué se contaba. De ahí la nota de
> arriba: **una cifra sin su denominador envejece mal y no se puede reproducir**.
> Si una cifra no se puede volver a medir con un comando, se retira en vez de
> arrastrarla; es lo mismo que esta auditoría le exige al producto.

Documentos hermanos, que esta auditoría no repite:
[frontend-data-invariants.md](frontend-data-invariants.md) (ADR-014) y
[frontend-motion.md](frontend-motion.md).

---

## Punto de partida

La disciplina técnica del frontend está por encima de la media y está
documentada: tokens de diseño en `web/src/app/globals.css`, un manual de
movimiento con presupuestos de duración reales, invariantes de integridad
analítica **bloqueantes en CI**, `eslint-plugin-jsx-a11y` en `error`, overlays
sobre Radix con focus trap, y un registro único del árbol de navegación con un
contrato por página de qué filtros aplica de verdad.

El problema, **cuando se escribió esta auditoría**, no era falta de rigor: era
que el producto estaba a mitad de una migración de modelo mental y esa costura se
veía. El comentario de entonces en `lib/navigation.ts` lo decía —*"Legacy
analytical routes stay in SECTIONS beneath Mercado … during the gradual
migration"*— y mientras tanto convivían dos arquitecturas de información, dos
lenguajes visuales de página y varias fuentes de verdad para el mismo dato.

**Esa migración terminó el 2026-08-03** (punto 2 de abajo): hoy hay un solo
registro, `lib/console-spaces.ts`, y `lib/navigation.ts` queda como catálogo de
páginas y contratos de filtros. El diagnóstico de esta sección se conserva porque
explica de dónde vienen los cinco problemas de abajo, no porque siga vigente.

Eso importa más aquí que en otro producto: TenderFlow vende **confianza en el
dato**. Cada incoherencia de formato o de etiquetado se cobra en credibilidad,
no solo en estética.

---

## Los cinco problemas estructurales

Severidad: **P0** rompe una promesa del producto · **P1** daño diario ·
**P2** fricción acumulada.

### 1 · El Radar prometía una priorización que no existía — **P0** ✅ resuelto en Ola 1

Página insignia del modelo nuevo, con tres defectos encadenados.

`hooks/use-radar.ts` pedía `/api/v1/licitaciones?limit=24&sort=fecha_publicacion`
y decoraba cada fila con su score sin reordenar. Los items se renderizaban **en
orden cronológico**, mientras el `<h1>` decía *"Qué merece atención ahora."*,
cada tarjeta abría con un badge `Score N` y la descripción en `navigation.ts`
prometía *"señales priorizadas"*. Es el anti-patrón 1 de
[frontend-data-invariants.md](frontend-data-invariants.md) en su forma más sutil:
no se fabricaba el número, se fabricaba **el orden**.

Además el score llegaba después del primer render (la query de scoring estaba
`enabled` tras resolver el listado) y el hueco se rellenaba con `"Nueva señal"`,
que se lee como una categoría del dato y no como "todavía no lo sé".

Y el descarte vivía en `React.useState`: **no hay endpoint de dismiss en el
backend** (verificado: cero coincidencias en `api/`, `services/`, `db/`). El
usuario triaba 24 señales, recargaba, y volvían las 24. Ni siquiera llegaba a
`localStorage`, que el propio invariante 2 ya considera insuficiente.

**Hecho:** orden por el score del backend (los no puntuados al final), badge en
skeleton mientras el ranking está en vuelo, alcance declarado en la UI,
descarte con *undo* por ítem y copy que dice que es de sesión, y los
expedientes en estado terminal (RES/ADJ/ANUL) fuera de la bandeja vía
`solo_abiertas` en `GET /licitaciones` — el corte se aplica en backend para no
encoger las 24 filas que la página promete.

**Cerrado del todo (2026-08-07, commits `8eb7450` y `ad2574e`).** El ranking
real ya se consume: `ScoredOpportunity` incluye los campos que la tarjeta pinta
(`fecha_limite`, `tecnologia`, `cpv`, `ccaa`, `estado`, `url`…), así que
`hooks/use-radar.ts` usa `GET /analytics/scoring?limit=24` como fuente única —
el top-24 del corpus abierto, no una ventana cronológica reordenada. Y el
descarte es server-side (`/api/v1/radar/dismissals`, migración v76): recargar
conserva el triaje.

### 2 · Dos arquitecturas de información, tres componentes contando historias distintas — **P1** ✅ resuelto

`lib/navigation.ts` declara dos árboles: `PRODUCT_SPACES` (Radar / Oportunidades
/ Mercado) y `SECTIONS` (12 secciones analíticas). Los tres componentes de
navegación exponían cortes distintos del mismo árbol:

| Componente | Qué exponía |
|---|---|
| Sidebar | `PRODUCT_SPACES` + un enlace por sección al `pages[0]`. **~11 destinos para 28 páginas** |
| Breadcrumb | `Espacio › Página`, **saltándose el nivel Sección** — justo al que enlaza la sidebar |
| PageTabs | El nivel Sección, pero solo si tiene más de una página |

Lo más grave era que el breadcrumb **mentía**: `findProductSpace` devolvía
`Mercado` para cualquier ruta que no fuese radar/oportunidades, así que
anunciaba **"Mercado › Administración"** y **"Mercado › Calidad de Datos"**, con
enlace a `/resumen`. La sidebar iluminaba "Mercado" con el mismo criterio.

Y colapsar la sidebar **borraba** la navegación en vez de comprimirla:
`{!collapsed && marketSections.map(…)}` desmontaba 10 de 12 secciones, dejando 3
destinos de 11.

**Hecho:** `NavSection.space` declara la pertenencia en vez de inferirla por
descarte; breadcrumb con los tres niveles reales, colapsando el nivel que
duplique a un vecino; sidebar colapsada como rail de iconos con Tooltip y nombre
accesible; preferencia de colapso persistida.

**Cerrado del todo (2026-08-03).** La unificación se hizo: `CONSOLE_SPACES` +
`SPACE_VIEWS` (`lib/console-spaces.ts`) son la única fuente, y el cromo heredado
—`top-nav`, `sidebar`, `global-filter-bar`, `breadcrumb`, `page-tabs`, `kpi-bar`
y `PRODUCT_SPACES`/`SECTIONS`— se demolió con sus tests. Ya no hay dos árboles,
así que "Mercado" ha dejado de estar dentro de sí mismo y el breadcrumb no tiene
ningún nivel que colapsar. Hoy son **14 espacios** que absorben las rutas
heredadas como `?vista=` (medido el 2026-08-27).

Antes de eso, tres rutas quedaban fuera de la navegación: `/licitadores`
(redirect deliberado) y `ecosistema-partners` / `red-organo-empresa`, dos páginas
completas a las que no se llegaba desde ninguna parte — rescatadas como vistas
experimentales en el commit `0f55f2c`.

### 3 · Cinco formateadores de moneda, y el más visible estaba mal — **P1** ✅ resuelto en Ola 1

`lib/utils.ts` ya exponía `formatCurrency`/`formatNumber`/`formatDate` sobre
`Intl`, y aun así había cuatro implementaciones locales que lo ignoraban
(`kpi-bar`, `pursuit-presenters`, `active-learning`, `mi-perfil`).

La del KPI bar —**la cifra más visible de la aplicación**— tenía dos bugs de
localización: emitía `"2.5B €"` para 2.500 millones, y en castellano **B se lee
billón (10¹²)**, así que presentaba un importe mil veces mayor del real. Y usaba
`.toFixed(1)`, que produce punto decimal (`1.5M €`) en la misma barra donde
`formatNumber` produce punto de millares (`1.234.567`): el mismo carácter con dos
significados opuestos a 40 píxeles de distancia.

En paralelo, **dos indicadores de frescura simultáneos** consultando endpoints
que miden cosas distintas: la sidebar leía `last_scrape_hours_ago` de
`/analytics/quality` (cuándo terminó el último *run*) y el TopNav
`/meta/last-extraction` (`MAX(fecha_extraccion)`, cuándo se selló el dato). Un
run que no encuentra nada nuevo mueve uno y no el otro, así que podían discrepar
en pantalla.

**Hecho:** `formatCompactCurrency` sobre `Intl`, los cuatro locales delegando,
marcador único de "sin dato" (`EMPTY`, `—` — antes convivían `-` y `—`), y
`useDataFreshness` como fuente única (de paso desaparece un sondeo de 60 s a un
endpoint de analytics en cada carga de página).

### 4 · El chrome se comía la pantalla y los controles que lo aliviaban no funcionaban — **P2** ✅ resuelto en Ola 1

Antes del `<h1>` de cualquier página: TopNav 60px sticky + KpiBar `min-h-11` +
GlobalFilterBar `min-h-13` sticky + Breadcrumb + PageTabs + cabecera. **~230px
fijos** en un layout cuyo contenido son tablas densas y grafos.

Los dos mecanismos que debían compensarlo estaban rotos o ausentes:

- **El toggle de densidad era un no-op.** Aplicaba
  `compact && "[&_.container]:px-2 …"`, y la clase `.container` tiene **cero
  usos** en todo `web/src`.
- **`PageHeader` era código muerto**: componente completo, con test propio, y
  **ningún fichero lo importaba**. De ahí la divergencia visual — `radar`,
  `oportunidades` y `login` con `tf-display` y secciones hero; el resto con
  `tf-h1` plano. Dos lenguajes por omisión, no por decisión.
- **La GlobalFilterBar hacía `flex-wrap`** con hasta 8 controles más un chip por
  filtro activo, en una barra `sticky`.

**Hecho:** densidad vía `data-density` + `data-slot` en los primitivos; variante
`hero` en `PageHeader` y adopción en Radar/Oportunidades/Resumen; la barra de
filtros pasa a una fila con scroll horizontal al scrollear.

### 5 · Accesibilidad bien cimentada, mal rematada — **P1** ◐ parcialmente resuelto

Lo cimentado es real y poco común: `jsx-a11y` en `error`, `:focus-visible`
global, `prefers-reduced-motion` / `prefers-reduced-transparency` /
`prefers-contrast` tratados con matiz, overlays Radix. Los remates que faltaban
pesaban más de lo que parece:

| Hallazgo | Estado |
|---|---|
| **Un solo `aria-live` en toda la app** (`login/page.tsx`). Filtrar, pasar de skeleton a datos o ver el total saltar de 4.000 a 12 era silencioso — en un producto cuya interacción central es filtrar y leer el recuento | ✅ `components/live-region.tsx` + `useAnnounceOnChange` en `DataTable` y `GlobalFilterBar` |
| **`accessibilityLayer` de Recharts: 0 usos en 18 ficheros.** Es un prop; sin él cada gráfico es un SVG sin recorrido por teclado | ✅ 36 gráficos cartesianos; el sparkline queda `aria-hidden` por decorativo |
| **El skip link no movía el foco**: apuntaba a un `<div id="main">` sin `tabIndex={-1}`, y había un segundo enlace compitiendo. En `/login` apuntaba a un ancla inexistente | ✅ una sola ancla, `tabIndex={-1}`, landmark `main` en login |
| **`app/global-error.tsx` no existía**: un fallo en el layout raíz caía en la pantalla por defecto de Next, en inglés y sin marca | ✅ |
| **`<Toaster />` vivía en `(dashboard)/layout.tsx`**: todo `toast()` disparado en `/login` se descartaba en silencio | ✅ montado en `Providers`, que hoy cuelga de `(dashboard)/layout.tsx` **y** de `login/layout.tsx`. Pasó por el layout raíz, pero desde ahí lo heredaba también la superficie pública, que no dispara toasts y no debía cargar el runtime del dashboard. El invariante es el de siempre: un `toast()` en `/login` tiene que verse |
| **Atajos que secuestraban la escritura**: el guard solo excluía `input`/`textarea`, así que con el foco en un `contenteditable` o un listbox de Radix pulsar `1` te sacaba de la página. Y los 5 atajos apuntaban a páginas legacy, ninguno a Radar ni Oportunidades | ✅ guard ampliado, modificadores respetados, `1`–`6` incluyen los espacios primarios |
| **Atajos indescubribles**: solo ⌘K estaba anunciado | ✅ overlay `?`, derivado de `NUMBER_SHORTCUTS` para que no driftee |
| **192 `title=` nativos** frente a un `Tooltip` de Radix ya construido. El `title` nativo no se dispara con teclado | ◐ migrados los de la cabecera y los controles icon-only; **quedan 137** (medidos el 2026-08-27), sobre todo celdas de tabla y textos truncados |
| **Ortografía castellana rota** en decenas de cadenas visibles, incluida la meta description del sitio | ◐ hechas las superficies de mayor visibilidad; el barrido completo queda pendiente |

---

## Hallazgos menores, no cubiertos por la Ola 1

Estado revisado contra el código el 2026-08-27. Los hallazgos que citaban
ficheros hoy inexistentes se han reescrito o retirado: un hallazgo que apunta a
un fichero borrado hace que quien lo coja empiece por un callejón sin salida.

| Hallazgo | Evidencia | Prioridad |
|---|---|---|
| ~~`e2e/responsive.spec.ts` es un test vacío~~ ✅ **resuelto** (`197df83`): tres casos reales de drawer móvil y rail de escritorio, sin `.or()` ni condicionales | `web/e2e/responsive.spec.ts` | — |
| ~~`vitest.config.ts` excluye `src/app/**` de cobertura~~ ✅ **corregido el 2026-08-10**: solo se excluyen `layout/loading/error/not-found`, y `src/app/**/_hooks/*.ts` se mide. Lo que sigue abierto es la cobertura en sí, no el denominador | `web/vitest.config.ts` | ver backlog |
| Páginas grandes sin descomponer. **Las tres que citaba esta fila ya bajaron** al extraer su lógica a `_hooks/`: `detalle` 929 (era 1.015), `mi-watchlist` 917 (1.044), `competidores` 867 (1.047). Siguientes por tamaño, aún sin `_hooks/`: `tecnologias` 734, `organos` 649, `radar` 635 | medido 2026-08-27 | P2 |
| ~~`radar/page.tsx` y `oportunidades/page.tsx` en estilo comprimido~~ — retirado: `oportunidades` son hoy 245 líneas y `radar` 635, ambas reescritas desde entonces. La afirmación sobre su legibilidad no se ha vuelto a comprobar, así que se retira en vez de repetirse | — | — |
| El selector de organización es un `<select>` nativo estilado, mientras el resto de controles son Radix: comportamiento de teclado y lector distinto. **Vive ahora en el rail**, no en la sidebar (demolida) | `layout/console-rail.tsx:125` | P2 |
| ~~Los filtros de CCAA / tecnología / estado son `<select>` nativos~~ ✅ resuelto 2026-08-07 (`352db1b`): `ui/multi-select.tsx` con Popover, búsqueda que ignora tildes (`foldText`) y quitar desde el propio control | `layout/scope-bar.tsx` | — |
| Por debajo de `md` el rail de espacios es `hidden` y el drawer es la única navegación. **Ya no es un agujero de verificación** —el e2e lo cubre—, sino de diseño: lo que hay detrás del drawer son tablas densas pensadas para escritorio | `layout/console-rail.tsx:196,242` | P2 |
| ~~`next.config.ts` describe la CSP como Report-Only~~ ✅ **el comentario ya dice lo contrario** ("no Report-Only", `next.config.ts:11`) | `web/next.config.ts` | — |
| ~~`/licitadores` conserva `layout.tsx` y `loading.tsx`~~ ✅ **resuelto**: el directorio solo contiene `page.tsx` | `app/(dashboard)/licitadores/` | — |

**Corrección respecto a una lectura inicial:** `/licitadores` **no** es una ruta
huérfana. Es un *redirect* deliberado a `/competidores` (consolidación
documentada en su RFC) que existe para no romper deep-links guardados; su
ausencia del registro de navegación es correcta.

---

## Decisiones de producto

**1. ¿El producto es español-only? — DECIDIDA: sí, y ejecutada.** La capa de i18n
vestigial ya no existe: `lib/i18n.ts` y `public/locales/` están **borrados** del
árbol, y la retirada quedó documentada donde deja huella, en `web/src/proxy.ts`
("`/locales` salió con la retirada de i18n (el producto es español-only): era una
ruta exenta del control de sesión sin nada detrás"). Se ejecutó en `b070c0e`
(PR #154, 2026-08-08), o sea que esta auditoría llevaba **casi tres semanas
listando como pregunta abierta algo que ya tenía respuesta en el código**.

Consecuencia para el trabajo futuro, que es lo único que esta sección tiene que
decir ahora: **no se añaden `t()` ni ficheros de locale ad hoc**. Si alguna vez
se quiere un segundo idioma, es una decisión nueva y empieza por extraer las
cadenas, no por reintroducir media capa.

**2. ¿Se unifican los dos árboles de navegación, y cuándo? — DECIDIDA y
ejecutada.** `CONSOLE_SPACES` + `SPACE_VIEWS` son hoy la única fuente y
`PRODUCT_SPACES`/`SECTIONS` desaparecieron (ver _Cerrados_ del backlog,
2026-08-03). Se conserva el párrafo de abajo porque explica por qué el breadcrumb
de entonces tenía que colapsar niveles, no porque siga habiendo nada que decidir.

Mientras estuvo abierta, cualquier arreglo de navegación fue contención: el
breadcrumb tenía que colapsar niveles duplicados porque "Mercado" era a la vez
espacio y sección, y la sidebar mantenía dos listas con criterios distintos.

**Las decisiones que sí siguen abiertas hoy no son de UI**, y viven en el
backlog con su coste declarado: el `plan: free` de la API frente al SLO del 99 %,
y si la allowlist de acceso deja de ser una variable de entorno editada a mano
(esa además necesita RFC: toca auth y migración).

---

## Roadmap

**Ola 1 — hecha.** Los cuatro ejes de arriba, en cuatro commits temáticos.

**Ola 2 — hecha del todo.** Sus tres puntos están cerrados y verificados en el
código el 2026-08-27:
1. Dismiss del Radar server-side y `GET /analytics/scoring?limit=24` como fuente
   única (commits `8eb7450`/`ad2574e`, squash `b070c0e`) — ver el punto 1 arriba.
2. `e2e/responsive.spec.ts` es un test real: tres casos a 375×812 y 1440×900 que
   exigen el drawer, un destino concreto (`/radar`) y su cierre, **sin `.or()`,
   sin `if`, sin `.catch()`**. Cae si se elimina el drawer (`197df83`).
3. `ui/multi-select.tsx` sustituye a los `<select>` nativos de los filtros
   (`352db1b`, squash `b070c0e`). Queda **uno** sin migrar, el de organización
   del rail (`console-rail.tsx:125`); está en el backlog con la experiencia móvil.

**Ola 3 — hecha.** La unificación de árboles se ejecutó el 2026-08-03: hoy hay un
solo registro (`CONSOLE_SPACES`/`SPACE_VIEWS`) y el cromo heredado se demolió.

**Continuo:** migración de los `title=` restantes a `Tooltip` (**137** hoy, desde
los 192 del original), barrido de ortografía, y descomposición de las páginas
grandes — la vía que funcionó es extraer a `_hooks/`, hecha en `detalle`,
`mi-watchlist` y `competidores`.
