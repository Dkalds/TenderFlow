# Auditoría UX/UI del frontend

Revisión crítica de `web/` (Next.js 16, App Router) hecha el 2026-08-01. Las
cifras del original —28 rutas de dashboard, ~27k LOC de TSX— se quedaron atrás
enseguida: a 2026-08-10 son 33 rutas y ~44,7k LOC de TS/TSX. Prioriza por daño al usuario, no por
esfuerzo. La **Ola 1** ya está implementada; el resto está priorizado abajo y
replicado en [IMPROVEMENT_BACKLOG.md](IMPROVEMENT_BACKLOG.md).

Documentos hermanos, que esta auditoría no repite:
[frontend-data-invariants.md](frontend-data-invariants.md) (ADR-014) y
[frontend-motion.md](frontend-motion.md).

---

## Punto de partida

La disciplina técnica del frontend está por encima de la media y está
documentada: tokens de diseño en `web/src/app/globals.css`, un manual de
movimiento con presupuestos de duración reales, invariantes de integridad
analítica **bloqueantes en CI**, `eslint-plugin-jsx-a11y` en `error`, overlays
sobre Radix con focus trap, y `lib/navigation.ts` como fuente única del árbol de
navegación con un contrato por página de qué filtros aplica de verdad.

El problema no es falta de rigor. Es que **el producto está a mitad de una
migración de modelo mental y esa costura es visible para el usuario**. El
comentario de `lib/navigation.ts` lo dice: *"Legacy analytical routes stay in
SECTIONS beneath Mercado … during the gradual migration"*. La migración no ha
terminado, y mientras tanto conviven dos arquitecturas de información, dos
lenguajes visuales de página y varias fuentes de verdad para el mismo dato.

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

### 2 · Dos arquitecturas de información, tres componentes contando historias distintas — **P1** ◐ parcialmente resuelto

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

**Pendiente (P1, backlog):** la unificación de verdad — fundir `PRODUCT_SPACES`
y `SECTIONS` en un solo árbol. Mientras existan dos, "Mercado" es a la vez un
espacio y una sección dentro de sí mismo, y el breadcrumb tiene que colapsar ese
nivel para no decir "Mercado › Mercado › Órganos". Toca las 28 rutas; merece su
propia rama.

**Corregido el 2026-08-07:** este recuento quedó obsoleto con la migración a
espacios de consola. Hoy son **13 espacios que absorben 19 vistas**, y solo tres
rutas quedaban fuera de la navegación: `/licitadores` (redirect deliberado) y
`ecosistema-partners` / `red-organo-empresa`, dos páginas completas a las que no
se llegaba desde ninguna parte — rescatadas como vistas experimentales en el
commit `0f55f2c`.

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
| **`<Toaster />` vivía en `(dashboard)/layout.tsx`**: todo `toast()` disparado en `/login` se descartaba en silencio | ✅ movido al layout raíz |
| **Atajos que secuestraban la escritura**: el guard solo excluía `input`/`textarea`, así que con el foco en un `contenteditable` o un listbox de Radix pulsar `1` te sacaba de la página. Y los 5 atajos apuntaban a páginas legacy, ninguno a Radar ni Oportunidades | ✅ guard ampliado, modificadores respetados, `1`–`6` incluyen los espacios primarios |
| **Atajos indescubribles**: solo ⌘K estaba anunciado | ✅ overlay `?`, derivado de `NUMBER_SHORTCUTS` para que no driftee |
| **192 `title=` nativos** frente a un `Tooltip` de Radix ya construido. El `title` nativo no se dispara con teclado | ◐ migrados los de la cabecera; el resto pendiente |
| **Ortografía castellana rota** en decenas de cadenas visibles, incluida la meta description del sitio | ◐ hechas las superficies de mayor visibilidad; el barrido completo queda pendiente |

---

## Hallazgos menores, no cubiertos por la Ola 1

| Hallazgo | Evidencia | Prioridad |
|---|---|---|
| `e2e/responsive.spec.ts` es un test vacío: asigna `_hamburger` y nunca lo usa; solo comprueba que `body` es visible. La experiencia móvil no tiene cobertura real | `web/e2e/responsive.spec.ts` | P1 |
| `vitest.config.ts` excluye `src/app/**` de cobertura, y ahí vive la mayor parte de la lógica (12 páginas superan las 500 líneas) | `web/vitest.config.ts` | P2 |
| Páginas gigantes sin descomponer: `mi-watchlist` 1072 LOC, `competidores` 988, `active-learning` 865. El patrón `_components/` solo se aplicó en `resumen` y `pipeline-alertas` | — | P2 |
| `radar/page.tsx` y `oportunidades/page.tsx` están escritas en estilo comprimido (líneas de 900 caracteres con ternarios anidados). Son los dos ficheros más difíciles de modificar con seguridad, y los más nuevos | — | P2 |
| El selector de organización de la sidebar es un `<select>` nativo estilado, mientras el resto de controles son Radix: comportamiento de teclado y lector distinto | `layout/sidebar.tsx` | P2 |
| ~~Los filtros de CCAA / tecnología / estado son `<select>` nativos~~ ✅ resuelto 2026-08-07 (`352db1b`): `ui/multi-select.tsx` con Popover, búsqueda que ignora tildes (`foldText`) y quitar desde el propio control | `layout/scope-bar.tsx` | — |
| La sidebar es `hidden md:flex`: por debajo de `md` el conmutador de espacios de producto no existe, solo el drawer del TopNav | `layout/sidebar.tsx` | P2 |
| `next.config.ts` describe la CSP como Report-Only, pero `middleware.ts` la aplica: comentario obsoleto respecto al código | `web/next.config.ts` | P3 |
| `/licitadores` conserva `layout.tsx` (con `metadata.title`) y `loading.tsx` para una ruta que solo hace `redirect("/competidores")` | `app/(dashboard)/licitadores/` | P3 |

**Corrección respecto a una lectura inicial:** `/licitadores` **no** es una ruta
huérfana. Es un *redirect* deliberado a `/competidores` (consolidación
documentada en su RFC) que existe para no romper deep-links guardados; su
ausencia de `navigation.ts` es correcta.

---

## Decisiones de producto abiertas

No las toma un agente. Las dos condicionan trabajo futuro:

**1. ¿El producto es español-only?** Hoy hay una capa de i18n vestigial:
`lib/i18n.ts` + `public/locales/{es,en}.json` con 40 claves cada uno, `t()`
usado en 12 ficheros y casi siempre para una o dos cadenas, **ningún selector de
idioma en ninguna parte**, y `<html lang="es">` fijo. `en.json` es inalcanzable.
Si la respuesta es "sí, español-only", lo honesto es retirar la capa en vez de
mantener algo que aparenta i18n y no lo es. Si es "no", hay que completarla —
extraer ~2.000 cadenas hardcodeadas—, no ampliarla ad hoc.

**2. ¿Se unifican los dos árboles de navegación, y cuándo?** La migración lleva
abierta desde que se introdujeron los espacios de producto. Mientras siga
abierta, cualquier arreglo de navegación es contención: el breadcrumb tiene que
colapsar niveles duplicados porque "Mercado" es a la vez espacio y sección, y la
sidebar mantiene dos listas con criterios distintos.

---

## Roadmap

**Ola 1 — hecha.** Los cuatro ejes de arriba, en cuatro commits temáticos.

**Ola 2 — confianza y cobertura** (recomendada a continuación):
1. Endpoint de dismiss del Radar + `fecha_limite`/`tecnologia` en
   `ScoredOpportunity`, y cambiar el Radar a `scoring?limit=N`. Cierra el P0 de
   verdad.
2. Convertir `e2e/responsive.spec.ts` en un test real.
3. Filtros multi-select sobre `ui/select.tsx` en vez de `<select>` nativos.

**Ola 3 — el cambio estructural:** unificar `PRODUCT_SPACES` y `SECTIONS` en un
solo árbol y rehacer sidebar/breadcrumb/tabs encima. Es el de mayor impacto y el
que toca las 28 rutas.

**Continuo:** migración de los `title=` restantes a `Tooltip`, barrido de
ortografía, descomposición de las páginas gigantes.
