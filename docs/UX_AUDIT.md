# Auditoría UX/UI del frontend

Revisión crítica de `web/` (Next.js 16, App Router) hecha el 2026-08-01, repasada
el 2026-08-27. Prioriza por daño al usuario, no por esfuerzo. La **Ola 1** ya está
implementada; el resto está priorizado abajo y replicado en
[IMPROVEMENT_BACKLOG.md](IMPROVEMENT_BACKLOG.md).

**Alcance, y una corrección de 2026-09-03.** Hasta esa fecha este documento decía
auditar `web/` entero y sólo miraba la consola autenticada: los cinco problemas
estructurales, las tres olas y el continuo son todos del dashboard. La superficie
pública —la portada, los índices, las fichas y las páginas de evidencia— no había
pasado nunca por aquí, pese a ser lo único que ve alguien que no ha entrado. Su
revisión está al final, en «Superficie pública». Detrás va la tercera, del
2026-09-26, que no mira el flujo sino el aspecto: «Aspecto de plantilla en la
consola».

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
  `tf-h1` plano. Dos lenguajes por omisión, no por decisión. *(2026-09-26:
  `tf-display` y `tf-h1` ya no existen; el titular de espacio es `font-display
  text-tf-lede` y una clase retirada no pasa el lint. Ver «Aspecto de plantilla
  en la consola».)*
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
| **192 `title=` nativos** frente a un `Tooltip` de Radix ya construido. El `title` nativo no se dispara con teclado | ◐ migrados los de la cabecera y los controles icon-only; **quedan 137** (medidos el 2026-08-27), sobre todo celdas de tabla y textos truncados. *Estado (2026-09-19):* ✅ **0** — los últimos 36 migrados a `Tooltip`/`Pista` en `fe4a28d5` (2026-09-18); `scripts/check_title_attrs.py` con techo 0 |
| **Ortografía castellana rota** en decenas de cadenas visibles, incluida la meta description del sitio | ◐ hechas las superficies de mayor visibilidad; el barrido completo queda pendiente. *Estado (2026-09-19):* ✅ barrido cerrado con gate — `scripts/check_ortografia_ui.py` da 0 hallazgos (C7.8 del plan complementario) |

---

## Hallazgos menores, no cubiertos por la Ola 1

Estado revisado contra el código el 2026-08-27. Los hallazgos que citaban
ficheros hoy inexistentes se han reescrito o retirado: un hallazgo que apunta a
un fichero borrado hace que quien lo coja empiece por un callejón sin salida.

| Hallazgo | Evidencia | Prioridad |
|---|---|---|
| ~~`e2e/responsive.spec.ts` es un test vacío~~ ✅ **resuelto** (`197df83`): tres casos reales de drawer móvil y rail de escritorio, sin `.or()` ni condicionales | `web/e2e/responsive.spec.ts` | — |
| ~~`vitest.config.ts` excluye `src/app/**` de cobertura~~ ✅ **corregido el 2026-08-10**: solo se excluyen `layout/loading/error/not-found`, y `src/app/**/_hooks/*.ts` se mide. Lo que sigue abierto es la cobertura en sí, no el denominador | `web/vitest.config.ts` | ver backlog |
| Páginas grandes sin descomponer. **Las tres que citaba esta fila ya bajaron** al extraer su lógica a `_hooks/`: `detalle` 929 (era 1.015), `mi-watchlist` 917 (1.044), `competidores` 867 (1.047). Siguientes por tamaño, aún sin `_hooks/`: `tecnologias` 734, `organos` 649, `radar` 635. *Estado (2026-09-19):* ✅ **resuelto** — ESLint aplica `max-lines: 300` a todo `src/app/**` sin allowlist (`web/eslint.config.mjs`, vacía desde el 2026-09-08, S7.1 del plan v2); hoy ningún fichero de `src/app` pasa de 300 | medido 2026-08-27 | — |
| ~~`radar/page.tsx` y `oportunidades/page.tsx` en estilo comprimido~~ — retirado: `oportunidades` son hoy 245 líneas y `radar` 635, ambas reescritas desde entonces. La afirmación sobre su legibilidad no se ha vuelto a comprobar, así que se retira en vez de repetirse | — | — |
| ~~El selector de organización es un `<select>` nativo estilado, mientras el resto de controles son Radix~~ ✅ **resuelto** (*Estado 2026-09-19*): usa el `Select` de Radix con `aria-label="Organización activa"` | `layout/console-rail.tsx:138` | — |
| ~~Los filtros de CCAA / tecnología / estado son `<select>` nativos~~ ✅ resuelto 2026-08-07 (`352db1b`): `ui/multi-select.tsx` con Popover, búsqueda que ignora tildes (`foldText`) y quitar desde el propio control | `layout/scope-bar.tsx` | — |
| Por debajo de `md` el rail de espacios es `hidden` y el drawer es la única navegación. **Decisión 2026-09-01:** móvil cubre consulta y triaje (Radar, ficha, watchlist y agenda), no la edición completa de matrices analíticas. `responsive.spec.ts` fija que esos cuatro flujos no desborden el documento; las tablas bidimensionales pueden conservar scroll interno. *Estado (2026-09-19):* sin `fixme` en `responsive.spec.ts` y los rojos móviles del E2E corregidos en `8a424967`; el ítem del backlog está cerrado | `layout/console-rail.tsx`, `e2e/responsive.spec.ts` | — |
| ~~Scroll fantasma: un `absolute` sin ancestro posicionado dentro de una caja con scroll (los `sr-only`, los `<select>` nativos ocultos de Radix) toma el viewport como bloque contenedor, no se recorta y alarga el documento~~ ✅ **resuelto el 2026-09-26**: medido con datos reales, la ficha de oportunidad daba 1356/768 a 1366×768, el Resumen 841/812 a 375×812 y el rail 605/600 a 1280×600. **Regla:** toda caja con scroll en flujo del dashboard lleva `relative` (los overlays `fixed` ya son bloque contenedor); `responsive.spec.ts` mide el alto del documento. **Otras dos causas del mismo síntoma, que no son absolutos:** la franja de primer uso del ámbito sumaba su alto (84 px a 1366) a pantallas que medían `100vh - var(--alto-cromo)`, ✅ **resuelta el 2026-09-26**: el marco mide la pantalla, `#main-content` es la caja con scroll y las pantallas miden `h-full`, así que el cromo, sea el que sea, se descuenta solo (1366×768 con la franja: 768/768 en Resumen, Radar y Detalle). **Sigue abierta** la del Radar desde `xl`: la fila de acciones del inspector ocupa 445 px en una columna de 432, y la barra horizontal que eso abre ya no suma 10 px al documento, pero queda dentro de `#main-content` | `layout/space-shell.tsx`, `layout/console-frame.tsx`, `e2e/responsive.spec.ts`; abierto: `radar/_components/radar-inspector-acciones.tsx` | P2 |
| ~~`next.config.ts` describe la CSP como Report-Only~~ ✅ **el comentario ya dice lo contrario** ("no Report-Only", `next.config.ts:11`) | `web/next.config.ts` | — |
| ~~`/licitadores` conserva `layout.tsx` y `loading.tsx`~~ ✅ **resuelto**: el directorio solo contiene `page.tsx` | `app/(dashboard)/licitadores/` | — |
| ~~**Ficha de la oportunidad** (crítica del 2026-09-25): la primera pantalla funcionaba, pero debajo seguía el formulario antiguo apilado (4,2 pantallas a 1366×768); lo que faltaba para salir de la fase no se podía completar donde se veía; el importe de licitación no estaba en el Resumen; «Todos los campos» ofrecía un NO-GO y un cierre que el backend rechaza; el contraste contaba como requisitos los avisos de familia vacía; el historial pintaba `kit_item_marcado`~~ ✅ **resuelto el 2026-09-26**: cada paso pendiente lleva a su control (`lugar` en `_lib/salida-fase.ts`); oferta y responsable se editan en su celda; importe de licitación (o del lote) en la rejilla; columna de datos fija, también en «Pliego» y «Precio»; «Editar todos los campos» plegado y filtrado por fase (`decisionesPermitidas`); `requisitos_extraidos` y `sin_hechos` en el contrato del checklist; «Usar como oferta prevista» en los escenarios; pestañas con `aria-controls`, `tabpanel` y flechas. Lo fijan `datos-y-decision.test.tsx`, `salida-fase.test.ts`, `pursuit-editor.test.tsx` y `checklist-go-no-go.test.tsx`. El tamaño de letra (`cn()` y la escala `tf-*`) y el móvil van aparte, en #349 y #354 | `app/(dashboard)/oportunidades/[id]/` | — |

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
   *Estado (2026-09-19):* migrado a Radix `Select` (`console-rail.tsx:138`); el
   ítem de experiencia móvil está cerrado.

**Ola 3 — hecha.** La unificación de árboles se ejecutó el 2026-08-03: hoy hay un
solo registro (`CONSOLE_SPACES`/`SPACE_VIEWS`) y el cromo heredado se demolió.

**Continuo:** migración de los `title=` restantes a `Tooltip` (**137** hoy, desde
los 192 del original), barrido de ortografía, y descomposición de las páginas
grandes — la vía que funcionó es extraer a `_hooks/`, hecha en `detalle`,
`mi-watchlist` y `competidores`.
*Estado (2026-09-19):* los tres frentes están cerrados — `title=` en **0**
(`fe4a28d5`), páginas grandes bajo `max-lines: 300` en todo `src/app/**` sin
excepciones, y ortografía con gate propio (`scripts/check_ortografia_ui.py`,
0 hallazgos; C7.8 del plan complementario).

---

## Superficie pública

Revisada el 2026-09-03, por primera vez. La portada estaba bien construida por
dentro —Server Component, ISR, sin JavaScript salvo un beacon, cifras reales del
backend, formulario nativo, motion dentro del presupuesto— y aun así fallaba en
tres frentes que ninguna comprobación técnica veía.

### Roto en producción, no en el código

1. **El aviso legal publicaba un valor de relleno como responsable del
   tratamiento.** El guard del build sólo comprobaba que las variables
   `NEXT_PUBLIC_LEGAL_*` no estuvieran vacías. Cerrado: `lib/legal-placeholder.ts`
   rechaza también los valores de relleno, en el build y en render.
2. **Tres páginas publicadas y muertas.** `/cobertura`, `/metodologia` y
   `/seguridad` respondían 307 a `/login`: la misma decisión —«esta página es
   pública»— estaba escrita en cuatro listas independientes. Cerrado:
   `lib/rutas-publicas.ts` es la única, y `src/__tests__/rutas-publicas.test.ts`
   enumera los `page.tsx` del grupo para que la siguiente no nazca huérfana.
3. **El 404 público mandaba al dashboard**, o sea a `/login` para quien venía de
   un buscador. Cerrado con `(publico)/not-found.tsx`.

### Por qué se leía como una plantilla

El esqueleto era el de cualquier landing generada: píldora con icono, titular
centrado, captura con cromo de ventana de tres puntos, tarjetas con icono en
cuadrado tintado y numerales `01/02/03`, retícula de fondo con máscara radial,
resplandor en el cierre. La tipografía lo remataba —Space Grotesk sobre Geist, las
dos fuentes por defecto del sector—. Y la captura del hero enseñaba el producto
**degradado**: aviso de score degradado, identificadores del backend en crudo y
la etiqueta interna «ADR-014 · backend».

Cerrado en el mismo cambio: composición editorial (filetes en vez de tarjetas,
alineación a la izquierda, sin ornamento de fondo), Fraunces como fuente de
titulares **sólo** en la superficie pública —el dashboard conserva la suya, ver
`(publico)/layout.tsx`—, `lib/riesgos.ts` traduce los avisos que se pintaban en
snake_case, y `e2e/capturas-landing.spec.ts` regenera las imágenes desde el seed
en vez de tomarlas a mano.

*Estado (2026-09-26):* la consola dejó Space Grotesk y Fraunces pasó a ser la
fuente de titulares de toda la aplicación, declarada una vez en
`lib/tipografia.ts`. La frontera ya no es la superficie sino el tamaño:
`font-display` solo a partir de 15 px (D1 en «Aspecto de plantilla en la
consola»).

### El cambio de fondo

El hero enseñaba una **foto** del producto con datos de demostración. Ahora
enseña cinco expedientes reales del corpus público, servidos por la API
(`_components/ultimos-publicados.tsx`). Un producto cuyo argumento es la calidad
del dato no puede abrir con una imagen de datos inventados.

El copy pasó de 1.697 palabras visibles a 1.119, y el titular de 88 caracteres a
56. Lo que salió fue jerga —HHI, p10/p50/p90, CODICE, embeddings— que ahora vive
en las tres páginas de evidencia, enlazadas desde el cuerpo y desde el pie.

### Lo que queda abierto

- **La franja contradice al hero.** La portada cita el tamaño del corpus público
  mientras la migración v98 —que lo acota al universo tecnológico— siga sin
  aplicarse en producción (`migrate.yml` es manual). Hasta entonces la cifra es
  la del censo PSCP bajo un titular que promete lo contrario.
- **La variante clara de las capturas.** Se sirve una sola imagen, oscura, a
  quien tiene el sistema en claro. El script ya existe; falta generarlas y añadir
  el `<source media="(prefers-color-scheme: dark)">`.
- **Identidad publicada.** Razón social, NIF, domicilio y un buzón de contacto
  del dominio son variables de entorno que sólo el responsable puede rellenar.
- **Dominio propio.** El sitio se sirve desde `*.vercel.app`.

---

## Aspecto de plantilla en la consola (2026-09-26)

La tercera revisión, y la primera que no mira el flujo sino el aspecto: si la
consola se lee como UI generada por plantilla («vibecodeada»). Se hizo con
capturas de cada espacio en claro y en oscuro, contrastadas con las skills de
diseño del repo (`frontend-design`, `emil-design-eng`, `apple-design`,
`ui-ux-pro-max`, `web-design-guidelines` y `accessibility`): **55 hallazgos**
(F01–F55) en ocho temas —identidad, tipografía, ornamento, color y forma,
primitivos, voz, movimiento y puerta de entrada—, cada uno verificado después
contra el código. Se implementó el 2026-09-26/27 en la rama
`claude/app-appearance-improvement-5c04d4`: primero tokens, fuente, primitivos y
cromo (`46b6ab10`), después las pantallas, área por área.

**Denominador de las cifras de esta sección:** los `.ts`/`.tsx` de `web/src`
sin tests ni `src/generated/`, 679 ficheros en `28a624f8` (la base, antes de la
rama) y 697 hoy. Se cuentan con `git grep` sobre el ref y sobre el árbol, con
el bloque de comandos de «Qué se hizo». El grep también cuenta comentarios:
donde «hoy» no es cero por eso, se dice.

### Diagnóstico

TenderFlow no parecía vibecodeado por sus valores de base. El papel cálido, la
tinta y el naranja quemado estaban fijados por contraste y con test, la escala
`tf-*` bien pensada, los paneles planos y el movimiento con tokens. Lo que lo
delataba es que **nadie hacía cumplir esas decisiones**. La superficie pública
ya se había rediseñado con intención (sección anterior); sesión adentro, la
consola seguía con los valores del andamiaje:

- **La misma pieza, dibujada de 2 a 6 maneras**: vacío, error, KPI, conmutador
  de vista, chip y rótulo. El `Card` de shadcn —deprecado en un comentario que
  prometía una regla de lint nunca escrita— estaba en 106 ficheros, frente a 56
  con `Panel`; el vacío con baldosa tintada (`EmptyState`), en 28; el KPI con
  icono (`KpiCard`), en 14.
- **Una escala tipográfica que no mandaba**: 451 tamaños escritos a mano en 18
  valores (`text-[8.5px]`, `text-[10.5px]`…), 53 rótulos con la receta «mono +
  versal» a 8-10 px, la mono en cifras, fechas y palabras (216 usos), Space
  Grotesk de titular y el `h1` del espacio a 13 px, por debajo del botón
  «Exportar».
- **Color y forma ajustados sitio a sitio**: 29 opacidades distintas del
  naranja, 171 clases de la paleta cruda de Tailwind al margen de los tokens
  medidos por contraste, 19 radios fuera de escala más 90 `rounded` de 4 px, y
  44 paneles translúcidos (`bg-card/70`) sobre un fondo plano.
- **Los adornos que la portada ya había retirado**: el halo con ✨ del
  copiloto y Sparkles como comodín para «IA», «nuevo» y «buscar» (7 ficheros);
  un punto verde con `animate-ping` «en vivo» junto a datos de hace horas;
  emojis como iconos en la ficha de órgano; códigos de rail de tres letras en
  inglés; un login con red de partículas, retícula y tarjeta de cristal;
  NProgress; y los toasts con la paleta de demostración de Sonner.
- **Una voz sin dueño**: la interfaz narraba su arquitectura («calculada en
  backend», «sale de otro endpoint», «no se pinta»: 36 veces en 28 ficheros de
  la consola), los errores enseñaban rutas de API (19 `PanelError` con el
  `error.message` crudo) y convivían tuteo, voseo y vosotros (31 formas en 12
  ficheros), a veces en la misma frase.

### Decisiones del dueño (2026-09-26)

| # | Tema | Decisión |
|---|---|---|
| D1 | Titulares | Fraunces como `--font-display` de toda la aplicación, declarada una vez en `lib/tipografia.ts`, y **solo a 15 px o más**; por debajo, sans. Space Grotesk, fuera |
| D2 | Rótulos de dato | Sans, en frase, a 11 px (`ROTULO_DATO`), sin mono, sin versal y sin tracking. La versal queda solo en las cabeceras de columna (`CABECERA_COLUMNA`) |
| D3 | Rail | Palabra completa en castellano bajo cada icono, rail de ~72 px, un icono distinto por espacio |
| D4 | Puerta | Login, restablecer contraseña y 404 en el lenguaje de la portada: composición editorial a la izquierda y el formulario en un panel sólido; sin partículas, retícula, halo, cristal ni sombra |
| D5 | IA | Sparkles, fuera de todo el código: la IA se nombra, no se adorna |
| D6 | Errores | Mensaje humano, «Detalle técnico» plegado y Reintentar. **Un solo aviso por fallo**: lo que se pinta en línea no lanza además un toast |
| D7 | Cifra KPI | 20 px en sans con cifras tabulares; `StatStrip`/`StatCell` es el KPI canónico |
| D8 | Vocabulario | Se quedan «Score», «Pipeline», «Watchlist» y «Go/No-Go»; se traducen sync, win rate, dashboard, owner/admin, lead time, secret y API keys |

Y cuatro menores: la cabecera de cada espacio conserva su descripción, reescrita
como el trabajo que resuelve (F15); «ir a» es `EnlaceIr`, con hover solo de
color, porque lo que se ve decenas de veces al día no se desplaza (F35); el
rótulo público es uno, `KICKER` (F46); y NProgress se retira (F52). **No** se
hizo la portada del día (F27) ni se eligió el naranja de marca (F19).

### Las reglas de la casa

Lo que se aplicó a cada fichero, y lo que una pantalla nueva tiene que cumplir.
Los trinquetes de abajo y los comentarios de `web/eslint.config.mjs` citan estos
números.

1. **Tamaños**: la escala de `globals.css` y nada de `text-[Npx]`. De 8 a 11 px
   → `text-tf-micro`; 11,5-12 → `text-tf-meta`; 12,5-13,5 → `text-tf-body`; 14 →
   `text-sm`; 15 → `text-tf-lede`; 16-22 → `text-tf-title`; 24 o más →
   `text-tf-hero` o `text-tf-title`, según el papel.
2. **Mono** solo para identificadores y código: expediente, CPV, id externo,
   claves, hashes, `<code>`, `<kbd>` y atajos. Cifras, importes, fechas y
   palabras, en sans (las cifras tabulares ya son globales).
3. **Rótulos** con `ROTULO_DATO`, `SectionTitle`, `Fact` o `StatCell` de
   `console/panel`, y `CABECERA_COLUMNA` de `ui/table`; nada de recetas a mano.
4. **Titulares**: `font-display` solo a 15 px o más; títulos de panel
   `text-tf-body font-semibold`; en frase, sin Title Case inglés, y el título
   dice lo que se ve, no el tipo de gráfico.
5. **Superficies**: paneles en `bg-card` opaco; sin degradados decorativos;
   sombra solo en lo que flota (`shadow-md` en popover y menú, `shadow-lg` en
   modal); `tf-glass` solo donde de verdad pasa contenido por debajo.
6. **Tintes**: `primary` y los tonos semánticos en /5 (hover), /10
   (seleccionado, chip, fila activa) y /15 (énfasis; nunca más de /16 detrás de
   texto del mismo color, lo mide `contraste-tokens.test.ts`); bordes tintados
   en /30 o /50. Nada de la paleta cruda de Tailwind.
7. **Radios**: `rounded-md` en controles, chips y badges; `rounded-xl` en
   paneles; `rounded-full` en puntos y avatares. Nada de `rounded-2xl`,
   `rounded-[Npx]` ni `rounded` a secas.
8. **Iconos**: solo lucide, a `h-3`, `h-3.5` o `h-4`; sin icono decorativo
   delante de un título; nunca Sparkles, emojis ni un dólar para euros; un
   icono, un concepto (`lib/iconos.ts`).
9. **«Ir a»**: `EnlaceIr`; `ArrowUpRight`/`ExternalLink` solo para salir de
   TenderFlow; filas enlazadas enteras, sin flecha; «→» solo para rangos y
   cambios, y «›» para rutas («Mercado › Órganos»).
10. **Vacíos**: `PanelEmpty` con título y pista concretos; sin baldosa de icono
    ni caja de borde discontinuo.
11. **Errores**: `PanelError` con `error`; nunca rutas de API, códigos HTTP ni
    `error.message` crudos a la vista; y la consulta cuyo error se pinta en
    línea no lanza además un toast (`META_ERROR_EN_LINEA`).
12. **Avisos**: `Aviso` para las bandas info, warning, danger y success.
13. **Botones y conmutadores**: `Button` (`size="sm"` en la consola) y `Badge`;
    `PanelTabs` si hay panel, `Segmented` si es un filtro o un modo.
14. **Movimiento**: nada de stagger ni fundidos de entrada en lo que se
    consulta a diario; hover de filas y celdas solo de color; barras de
    puntuación sin transición; ≤ 200 ms en la UI operativa; sin pulsos
    infinitos decorativos.
15. **Voz**: castellano peninsular con tuteo, y la interfaz no narra su
    implementación. La honestidad de ADR-014 se dice en lenguaje de usuario
    («estimación», «parcial: solo las N primeras», «sin datos suficientes»),
    mejor en el pie o en una pista que en cada título.

### Qué se hizo

| Métrica | `28a624f8` | Hoy |
|---|---|---|
| Tamaños de letra a mano | **451**, en 18 valores | **0** |
| Rótulos «mono + versal» (líneas) | **53** | **0** |
| `uppercase` | 76 | 4: `CABECERA_COLUMNA`, el `KICKER` público y las dos imágenes OG |
| `font-mono` | 216 | 73, identificadores y código |
| Ficheros que importan `ui/card` · `ui/empty-state` · `charts/kpi-card` | 106 · 28 · 14 | **0 · 0 · 0** |
| Ficheros que importan `console/panel` | 56 | 246 |
| Ficheros con Sparkles | 7 | 0 (el grep da 1: un comentario de `lib/iconos.ts`) |
| Clases de la paleta cruda de Tailwind | 171 | 0 (el grep da 2: un comentario que cuenta cuáles se quitaron) |
| Opacidades distintas de `primary` | 29, en 181 usos | 12, en 143: los tintes de fondo van en /5, /10 o /15 (87 de 102 `bg-primary/N`) y los bordes en /30 o /50 (36 de 37) |
| `rounded-2xl`, `-3xl` o `-[Npx]` · `rounded` desnudo | 19 · 90 | 0 · 0 |
| Paneles translúcidos `bg-card/N` | 44 | 1: el aviso de reconexión, una capa `fixed` sobre contenido, justificada en su línea |
| `transition-[…transform…]`, que en Tailwind v4 no anima `scale-*` | 23 | 0 (el grep da 1: un comentario) |
| `animate-ping` · emojis | 1 · 6 | 0 · 0 |
| `PanelError` con `detail={….message}` | 19 | 1: el límite de error de los gráficos, plegado en «Detalle técnico» |
| Voseo o vosotros en texto visible · narración de la implementación en la consola | 31 en 12 ficheros · 36 en 28 | 0 · 0 |
| Rutas del dashboard con `loading.tsx` propio | 9 | 17: los 16 espacios y la ficha de oportunidad. El genérico solo cubre ya `/licitadores`, que es una redirección |

En la consola —`app/(dashboard)`, `components` y `app/login`— los tamaños
pasaron de `text-xs` ×372, `text-sm` ×362, `text-base` ×83 y `text-lg` a
`text-3xl` ×34, junto a 174 pasos `tf-*`, a 914 pasos `tf-*`, 20 `text-xs` o
`text-sm` y ningún `text-base` o mayor. Los primitivos ganaron el terreno que
dejaron las copias a mano: `PanelEmpty` en 94 ficheros (eran 16), `PanelError`
en 91 (23), con `META_ERROR_EN_LINEA` en 69 para no avisar dos veces, `Aviso` en
37, `Field` en 27, `StatStrip` en 26 (8), `CABECERA_COLUMNA` en 24, `EnlaceIr`
en 17, `Segmented` en 14 y `ChipBanda` —un solo chip de banda de puntuación— en
3.

Para volver a medirlo (bash, desde la raíz del repo; cada línea imprime
`antes -> hoy`):

```sh
# Denominador: 679 -> 697
git ls-tree -r --name-only 28a624f8 web/src | grep -E '\.tsx?$' | grep -vE '__tests__|\.test\.|/generated/' | wc -l
git ls-files --cached --others --exclude-standard web/src | grep -E '\.tsx?$' | grep -vE '__tests__|\.test\.|/generated/' | wc -l

P=(-- 'web/src/*.ts' 'web/src/*.tsx' ':(exclude)web/src/**/__tests__/**' ':(exclude)web/src/**/*.test.*' ':(exclude)web/src/generated/**')
n() { echo "$(git grep -ohE "$1" 28a624f8 "${P[@]}" | wc -l) -> $(git grep --untracked -ohE "$1" "${P[@]}" | wc -l)"; }  # apariciones
f() { echo "$(git grep -lE "$1" 28a624f8 "${P[@]}" | wc -l) -> $(git grep --untracked -lE "$1" "${P[@]}" | wc -l)"; }    # ficheros
n 'text-\[[0-9.][^]]*\]'
n 'font-mono[^"`]*uppercase|uppercase[^"`]*font-mono'
n '(^|[^a-z-])uppercase([^a-z-]|$)'
n 'font-mono'
f 'from "@/components/ui/card"'        # ídem ui/empty-state, charts/kpi-card, console/panel
f '(^|[^A-Za-z])Sparkles([^A-Za-z]|$)'
n '(bg|text|border|ring|fill|stroke|from|via|to|divide|outline)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-[0-9]{2,3}'
n '(bg|border|text|ring|from|via|to)-primary/([0-9]+|\[[^]]*\])'   # | sed 's|.*/||' | sort -u, para los valores distintos
n 'rounded-(2xl|3xl|\[)'
n '(^|[ "`:])rounded([ "`]|$)'
n 'bg-card/[0-9]'
n 'transition-\[[^]]*transform'
n 'animate-ping'
n 'detail=\{[^}]*\.message'
git grep -ohP '[\x{1F300}-\x{1FAFF}]' 28a624f8 "${P[@]}" | wc -l      # emojis
```

La voz no se cuenta con grep, porque un comentario que cita el texto antiguo
también casa: sale del escáner del test de voz (abajo), y la cifra de
`28a624f8` es ese mismo test con `SRC` apuntando a un `git archive 28a624f8
web/src`.

Lo que no cabe en una cifra:

- **Tipografía**: Geist, Geist Mono y Fraunces con eje óptico en
  `lib/tipografia.ts`. `text-tf-lede`, `-title` y `-hero` traen su peso y su
  tracking en el token, y salieron las utilidades muertas (`tf-display`,
  `tf-h1`, `tf-h2`, `tf-kpi`, `tf-caption`, `tf-card-shadow`,
  `tf-sidebar-surface`, `tf-hero-grid` y `tf-fill-enter`).
- **Cromo**: rail con palabras e iconos del mapa de `lib/iconos.ts` (un icono,
  un concepto); `h1` de espacio en `font-display text-tf-lede`; la frescura dice
  «Actualizado hace…», sin punto que late; barras sólidas.
- **Marca**: `lib/marca.ts` con el trazo TF y los hex actuales, del que beben el
  logo, las dos OG y `global-error`; el logo, sin halo.
- **Puerta** (D4): login, restablecer y 404 editoriales, y `/login` con la
  sesión abierta ofrece continuar (F55).
- **Movimiento**: duración y curva por defecto en `@theme`, `tf-pressable` que
  de verdad anima la escala, pulsación con tinte instantáneo en filas y tarjetas
  (F53), barras de puntuación sin transición (F37), y fuera el stagger de los
  KPIs, NProgress y `richColors` (`docs/frontend-motion.md`).
- **Errores y vacíos**: mensaje por estado en castellano (`lib/query-feedback.ts`),
  «Detalle técnico» plegado con la ruta para soporte, y vacíos con título y pista
  concretos.

### Trinquetes

Que lo conseguido se quede no puede depender de la revisión: la regla que
`ui/card.tsx` prometía desde su comentario nunca se escribió, y mientras tanto
la deuda de tamaños creció el doble de rápido que su migración. Cuatro
controles, los cuatro en el job `frontend` de CI (`npm run lint` y
`npm run test:coverage`) y en local con `npm run lint` y `npm run test`:

| Trinquete | Dónde | Qué impide | Allowlist |
|---|---|---|---|
| Primitivos retirados | `web/eslint.config.mjs`, `no-restricted-imports` (`importacionesRetiradas`) | Importar `ui/card`, `ui/empty-state` o `charts/kpi-card` fuera de sus tests | `deudaCard`: vacía desde que se escribió; solo encoge |
| Iconos retirados | La misma regla, con `importNames` de `lucide-react` | Sparkles y las varitas (D5); `DollarSign` y `CircleDollarSign` en un producto en euros; `AlertTriangle`, el nombre viejo de `TriangleAlert` | Ninguna |
| Aspecto | `web/eslint.config.mjs`, `no-restricted-syntax` (`restriccionesDeAspecto`), en todo `src` menos los tests, `src/lib` incluido | Tamaños a mano; la receta «mono + versal»; las clases retiradas de `globals.css`; la paleta cruda; radios fuera de escala; `bg-card/N`; `transition-[…transform…]`; `animate-ping` y `animate-bounce`; emojis y glifos (✓ ✕ ● ○) como iconos | Ninguna. Un caso legítimo se justifica en su línea (`eslint-disable-next-line no-restricted-syntax -- motivo`), como el aviso de reconexión |
| Voz | `web/src/__tests__/voz-de-la-interfaz.test.ts` (vitest, con el AST de TypeScript) | Voseo y vosotros en todo `src`; en la consola —todo menos `lib/` y `app/(publico)/`— «backend», «frontend», «endpoint», «servidor», «corpus», «fixture», «payload», «se pinta», «denominador», «renderiza»… | `EXCEPCIONES`: vacía; el test falla si una entrada deja de hacer falta |

Por qué así:

- **Solo miran lo que se pinta.** Las reglas de ESLint leen cadenas,
  plantillas y texto JSX; el test de voz, los nodos que pueden llegar a pantalla,
  sin comentarios, rutas de import, tipos, claves de objeto ni lo que va a
  `console.*`. Un comentario que cita la clase retirada para explicar por qué se
  fue no cuenta; el grep de la tabla de arriba sí, y por eso algunas cifras de
  «hoy» no son cero.
- **ESLint para clases e imports, un test para el texto.** ESLint se ve en el
  editor y en `npx eslint <fichero>`, que es como se verifica un cambio suelto.
  La voz necesita más: el voseo vivía también en toasts de hooks `.ts` y en
  texto JSX de varias líneas, que `scripts/check_ortografia_ui.py` —una regex por
  línea, sobre los `.tsx`— no ve; y la narración solo se prohíbe en la consola.
  Fuera quedan, a propósito, `lib/` (el contrato de mensajes de error dice «Error
  del servidor. Vuelve a intentarlo…», y `"corpus"` es el nombre de un ámbito
  que no se enseña) y `(publico)`, donde el aviso legal y la página de seguridad
  hablan del servidor porque es el dato exacto que tienen que dar.
- **En flat config, el último bloque que declara una regla la gana entera.**
  `restriccionesDeAspecto` se repite por referencia en los dos bloques de
  `no-restricted-syntax` que ya había y en uno nuevo para `src/lib`: añadir una
  restricción es añadirla a la constante.
- **Cada control se probó con un positivo conocido.** El test de voz empieza
  por una muestra con infracciones sabidas y comprueba que las encuentra, en la
  línea exacta (un escáner que no ve nada pasa siempre). Las reglas de ESLint se
  comprobaron igual, con un fichero de muestra por `--stdin` en
  `src/components`, `src/lib`, `app/(dashboard)` y un test (que queda fuera).
- **Lo que no se hizo trinquete, y por qué.** `role="tablist"` escrito a mano
  (F12): los tres que quedan son `PanelTabs`, la cabecera de espacio y el login,
  que comparten `useTeclasPestanas`, y el defecto de F12 eran conmutadores que
  *parecían* pestañas sin serlo, que una regla sobre el atributo no ve.
  `text-base` o mayor en la consola: hoy 0, pero la superficie pública los usa y
  la regla pediría un bloque por superficie. Las opacidades y los bordes de F10,
  que esperan a que la escala tenga nombre.

Comandos: `cd web && npm run lint` (0 errores) y `npx vitest run
src/__tests__/voz-de-la-interfaz.test.ts` (6 casos).

### Lo que queda

**Deuda medida:**

- **Borrar los primitivos retirados.** `ui/card.tsx`, `ui/empty-state.tsx` y
  `charts/kpi-card.tsx` ya solo los importan sus tests. Con ellos pueden irse
  `ExportPopover.className` (deprecado y sin llamadores) y `NavPage.icon` /
  `NavSection.icon` de `lib/navigation.ts`, que ya no se pintan.
- **Una escala de tintes con nombre (F10).** Quedan 12 opacidades de `primary`
  en 143 usos. Faltan los tokens (`primary-hover`, `-selected`, `-soft`) y un
  trinquete de opacidades sueltas. Los bordes, igual: `border-border/N` en 266
  usos de 152 ficheros, con siete valores de /25 a /80; un `--divider` solo puede
  entrar con el cambio de todos a la vez, o cada borde relativo se aclara un 30 %.
- **D6 en las mutaciones.** Muchas llevan el toast global del `MutationCache` y,
  además, su `onError` o su `catch` con otro toast (claves de API, cola de
  errores, usuarios, RGPD, formularios de equipo, etiquetas, oportunidades,
  tareas, comentarios…). Pide una decisión de conjunto —pasar el título local a
  `meta.errorTitle` o silenciar el global— y no es mecánico, porque los tests
  renderizan sin el `MutationCache`. Aparte, `useOrganizationMembers` tiene seis
  consumidores y solo `/equipo` pinta su error: silenciarla dejaría mudos cinco
  selectores.
- **Ortografía de reserva.** `CCAA_FALLBACK`
  (`mi-watchlist/_hooks/watchlist-rule-options.ts`: «Andalucia»,
  «Cataluna»…) se enseña tal cual si `/meta/filters` falla. Son valores que
  viajan al filtro: hace falta un mapa valor → etiqueta, como el de
  `spain-map.tsx`, no un reemplazo de texto.
- **El gate de tildes lee texto JSX de una sola línea.** Medido con el AST, hoy
  no esconde nada; pero el hueco existe (lo dice el propio script).
- `animate-pulse` queda en dos sitios, a propósito: el cursor que parpadea
  mientras se emite una respuesta (`chat-thread.tsx`, `licitacion-ai.tsx`),
  `motion-safe` y `aria-hidden`. Y ▲/▼ en Ops › Active learning es el signo de
  una tendencia junto a su cifra, no un icono.

**Hallazgos no hechos, o a medias:**

- **F27, la portada del día.** No se hizo, por decisión: `text-tf-hero` tiene 0
  usos en la consola y el Resumen sigue sin un titular del día.
- **F19, el naranja de marca.** Sin elegir entre #E8823E (el del favicon),
  #F39349 (el del tema oscuro y la OG) y #9A4513 (el óxido del tema claro). Está
  hecha la parte que no depende de él: `lib/marca.ts`, el logo sin halo y la OG
  con los textos de su fuente. Faltan los tokens `--brand`/`--brand-ink`, iguales
  en los dos temas y medidos por contraste, el favicon y un lockup con Fraunces
  local para Satori.
- **F24, el sello de puntuación** (cifra, banda y mecha en un solo dibujo). Está
  el chip de banda único, `ChipBanda`; el sello entero no cabe en la columna de
  46 px del Radar sin ensanchar la rejilla.
- **D8, «Ops y Admin»** (`lib/console-spaces.ts`, `ops/layout.tsx` y
  `ops/__tests__/views-shared.test.tsx`). El rail acabó en 84 px, no en ~72: a
  76 «Oportunidades» (77 px a 11 px) salía «Oportunidad…», y a 84 quedan 81 px
  de nombre. «Administración» cabría; «Ops y administración», no. Pendiente del
  dueño; si cambia, en los tres sitios a la vez.
- ~~**El Radar a 768 px desborda `#main-content` en horizontal.**~~ ✅
  **Resuelto el 2026-09-27.** La rejilla de la tabla (`RADAR_GRID`) suma ~766 px
  fijos antes del título y, con el rail de 84, a 768 px quedan 684: había 133 px
  de scroll lateral dentro de `main` (ya pasaba en master con el rail de 56). La
  tabla empieza ahora en `lg` (1024 px, donde al título le quedan ~164 px,
  descontada la barra de la lista); entre `md` y `lg` el Radar usa la ficha de
  móvil, con «Ver ficha» y el inspector como `Sheet`, y «Abrir» a su ancho de
  contenido. El umbral de JS (`MQ_TABLA_RADAR`, del que sale el `inert` de las
  acciones ocultas) es el mismo que el prefijo de Tailwind **y en su unidad**:
  los tres umbrales de `use-media-query.ts` pasaron de px a rem, porque el rem
  de una media query sigue la letra del navegador y, con la «Grande» de Chrome,
  `lg` son 1280 px; en px quedaban fichas visibles con las acciones `inert`.
  **Y a 1280 px el título medía 0.** Desde `xl` el inspector va anclado con
  432 px: con el rail de 84, a la tabla le quedan 764 y las siete columnas
  piden ~766 antes del título (con el rail de 56 ya estaba en ~16 px). Lo cazó
  el E2E de navegación, que corre a 1280. Desde `xl` la tabla no lleva columna
  de Tecnología —va en la línea secundaria del título, como en la ficha, y el
  inspector la repite— y Órgano cede 20 px: el título tiene ~150 px a 1280 y
  ~235 a 1366. `radar-grid.test.ts` hace esa cuenta con el rail y el inspector. Lo fijan `radar-grid.test.ts` (la cuenta a
  768 y a 1024), `page.test.tsx` y el E2E «Tableta vertical (768×1024)» de
  `responsive.spec.ts`. Detalle no cambia.
- `equipo/_components/anadir-miembro-form.tsx` conserva una caja de borde
  discontinuo. La regla 10 de la casa solo lo prohíbe en los vacíos; queda a
  criterio del dueño.
- **F55**: `mfa_required` en `AuthUser` solo si el backend lo manda en
  `/auth/me`.

**Sin verificar en la rama** (hacen falta una build o un backend sembrado):

- `next build` y `scripts/check_bundle_budget.py`.
- Los E2E: `accessibility` (toasts en `/ops?vista=webhooks` y en `/login`),
  `visual` (cambió la máscara de la franja de cifras), `responsive` (el rail a
  1280, 1366 y 1440 px con sesión de administración; y la fila del Radar ya no
  anima al pulsar J/K, así que la espera de `getAnimations` sobra), `login`,
  `seo`, `admin-guard`, `ajustes` y `pagina-cita`.
- Las capturas `.webp` de la portada (`npm run capturas:landing`), tomadas con
  la consola aún en Space Grotesk.
- `/graph-refresh`: se borraron `components/motion.tsx`, `route-progress.tsx`,
  `layout/particle-field.tsx` y `radar-inspector-piezas.tsx`, y se añadieron
  `lib/tipografia.ts`, `lib/marca.ts`, `lib/iconos.ts`, `ui/field.tsx` y
  `console/chip-banda.tsx`.
