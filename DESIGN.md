---
name: TenderFlow
description: Inteligencia de licitaciones TI del sector público español; consola densa, papel cálido, un solo acento.
colors:
  primary: "hsl(22 78% 34%)"
  primary-foreground: "hsl(36 100% 97%)"
  accent: "hsl(26 70% 92%)"
  accent-foreground: "hsl(22 75% 28%)"
  ring: "hsl(22 78% 34%)"
  background: "hsl(40 22% 96%)"
  foreground: "hsl(30 14% 10%)"
  card: "hsl(0 0% 100%)"
  muted: "hsl(42 14% 91%)"
  muted-foreground: "hsl(34 8% 34%)"
  secondary: "hsl(42 14% 91%)"
  secondary-foreground: "hsl(30 14% 12%)"
  border: "hsl(30 12% 40% / 0.28)"
  input: "hsl(30 12% 40% / 0.3)"
  shadow-ink: "hsl(30 20% 10%)"
  success: "hsl(150 70% 25%)"
  warning: "hsl(42 95% 25%)"
  info: "hsl(210 90% 37%)"
  destructive: "hsl(355 75% 42%)"
  primary-dark: "hsl(26 88% 62%)"
  background-dark: "hsl(30 8% 5%)"
  foreground-dark: "hsl(36 12% 93%)"
  card-dark: "hsl(30 8% 8%)"
  muted-foreground-dark: "hsl(34 8% 65%)"
typography:
  display:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 650
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  kpi:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.2
    fontFeature: "'tnum'"
  title:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.005em"
  body:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "0.8125rem"
    lineHeight: 1.4
    fontFeature: "'tnum'"
  meta:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "0.75rem"
    lineHeight: 1.35
  label:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.2
  label-column:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.04em"
  mono:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "0.75rem"
    lineHeight: 1.35
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "14px"
  full: "9999px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "8px 16px"
  button-primary-console:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.meta}"
    rounded: "{rounded.md}"
    height: "28px"
    padding: "0 10px"
  button-outline:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "8px 16px"
  button-ghost-hover:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.md}"
  input:
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "4px 12px"
  panel:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.xl}"
  badge-neutral:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
---

# Design System: TenderFlow

Lenguaje visual de `web/` (Next.js 16, React 19, Tailwind v4, primitivos Radix e
iconos lucide). **El código manda**: cada regla vive en el código o en el
documento que la decidió, y aquí se resume y se enlaza. El frontmatter de arriba
es la copia legible por máquina (la consumen Impeccable y su panel live) de los
tokens de `globals.css`; `tests/test_unit_design_md_tokens.py` falla si un valor
se desincroniza, así que un cambio de token se hace en los dos sitios en el
mismo commit. La verdad de producto (usuarios, voz, posicionamiento) está en
[PRODUCT.md](PRODUCT.md).

| Tema | Fuente de verdad |
|---|---|
| Tokens de color, sombras, radios, escala tipográfica, curvas | [web/src/app/globals.css](web/src/app/globals.css) |
| Familias tipográficas | [web/src/lib/tipografia.ts](web/src/lib/tipografia.ts) |
| Colores de marca fuera del navegador (OG, manifest, `global-error`) | [web/src/lib/marca.ts](web/src/lib/marca.ts) |
| Reglas de la casa y decisiones del dueño (D1-D8) | [docs/UX_AUDIT.md](docs/UX_AUDIT.md) |
| Movimiento | [docs/frontend-motion.md](docs/frontend-motion.md) |
| Invariantes de datos en el frontend | [docs/frontend-data-invariants.md](docs/frontend-data-invariants.md) |
| Trinquetes de aspecto (`restriccionesDeAspecto`) | [web/eslint.config.mjs](web/eslint.config.mjs) |

## Overview

**Creative North Star: "El parte de la mañana"**

Un boletín diario denso y fiable: se lee rápido, de arriba abajo, y cada cifra
lleva su fuente. La consola es una herramienta de trabajo para leer un mercado:
papel cálido, tinta oscura y un solo acento naranja para lo que se puede hacer.
La densidad es la de un documento de trabajo, no la de un panel de marketing.

La portada pública habla el mismo idioma con más aire y composición editorial
(texto a la izquierda, sin ornamento de fondo). Nada se mueve si no explica
algo; el movimiento completo está en [docs/frontend-motion.md](docs/frontend-motion.md).

**Key Characteristics:**

- Neutros cálidos de una sola familia y un único acento.
- Densidad alta en la consola: cuerpo a 13 px, cifras tabulares.
- Fraunces solo en titulares; todo lo demás en Geist.
- Paneles opacos con borde; la sombra solo en lo que flota.
- Movimiento corto (150 ms) y únicamente cuando explica un cambio.

## Colors

Papel y tinta cálidos con un naranja tostado como única voz de acción. Los
tokens viven en `:root` (claro) y `.dark` como tripletes HSL, expuestos a
Tailwind como `bg-background`, `text-foreground`, `border-border`, etc.

### Primary

- **Naranja tostado** (`primary`; en oscuro `primary-dark`): «lo que se puede
  hacer». Botón principal, enlaces de acción, anillo de foco (`ring`) y el tono
  de `accent` para hover y selección. No decora.

### Neutral

- **Papel** (`background`): el fondo de toda la aplicación; en oscuro
  `background-dark` (#0E0D0C).
- **Blanco de panel** (`card`): la superficie de paneles, popovers y campos.
- **Tinta** (`foreground`): texto principal.
- **Gris cálido** (`muted-foreground`): texto secundario, rótulos de dato.
- **Arena** (`muted`, `secondary`): fondos de chips, pistas y botones secundarios.
- **Línea** (`border`, `input`): bordes semitransparentes del mismo tono.
- **Tinta de sombra** (`shadow-ink`): tiñe sombras y el velo de modales
  (`bg-scrim`, al 50 %).

### Semantic

`success`, `warning`, `info` y `destructive`, más la rampa de urgencia y las
bandas de score. Sus luminosidades están fijadas por contraste WCAG, no por
gusto: [contraste-tokens.test.ts](web/src/lib/__tests__/contraste-tokens.test.ts)
recalcula los ratios leyendo `globals.css`, y un token que se aclare de más
rompe el test. Las series de gráficos (`--chart-1` … `--chart-10`) están
medidas a 3:1 como objeto gráfico.

### Named Rules

**The One Accent Rule.** El naranja es la única voz de acción; nada más en la
pantalla compite con él.

**The One Grey Family Rule.** Un solo gris, cálido, en todo el producto: nada de
pizarra (tono ~200) junto al papel, ni negro puro, ni la paleta cruda de
Tailwind (`bg-black`, `text-slate-500`…).

**The Tint Ladder Rule.** Tintes del mismo color a `/5` en hover, `/10` en
seleccionado y `/15` en énfasis; nunca más de `/16` detrás de texto del mismo
color.

## Typography

**Display Font:** Fraunces (con Georgia, serif)
**Body Font:** Geist (con system-ui)
**Label/Mono Font:** Geist Mono, solo para identificadores

**Character:** una serif con eje óptico para dar voz a los titulares sobre una
sans técnica y neutra que carga con todas las cifras.

### Hierarchy

Escala de seis pasos (`text-tf-*` en `globals.css`); el lint bloquea
`text-[Npx]`. La superficie pública trabaja con `text-sm`/`text-base` y tamaños
de titular propios.

- **Display** (`text-tf-hero`, 32 px, Fraunces): titular de portada y de
  pantalla destacada.
- **Headline** (`text-tf-title`, 20 px, Fraunces): titulares de sección.
- **KPI** (`text-tf-title`, 20 px, Geist con `tnum`): cifras de `StatCell`
  (decisión D7).
- **Title** (`text-tf-lede`, 15 px, 600): títulos de panel; en Fraunces solo
  cuando es titular.
- **Body** (`text-tf-body`, 13 px): cuerpo de la consola; el body activa `tnum`.
- **Meta** (`text-tf-meta`, 12 px): metadatos y botones `size="sm"`.
- **Label** (`text-tf-micro`, 11 px, 500): rótulos de dato (`ROTULO_DATO`), en
  frase.
- **Mono** (Geist Mono): expediente, CPV, ids, claves y `<kbd>`, nada más.

### Named Rules

**The Fifteen Pixel Rule.** Fraunces solo a 15 px o más (D1); por debajo,
Geist.

**The Sentence Case Rule.** Los rótulos de dato van en sans, en frase, a 11 px
(D2); la versal queda solo para cabeceras de columna (`CABECERA_COLUMNA`,
`label-column`).

## Layout

Consola densa para escritorio, organizada en espacios a los que se llega desde
el rail (D3). El móvil cubre consulta y triaje (Radar, ficha,
watchlist, agenda), no la edición de matrices.

- Alturas de pantalla completa en `dvh` (`h-dvh`, `min-h-dvh`), no `h-screen`:
  en iOS Safari `100vh` no descuenta la barra de direcciones.
- Los campos usan `text-campo`: 16 px en móvil (iOS no hace zoom al enfocar) y
  14 px desde `md`.
- La portada no usa filas de tres columnas iguales (`landing-como-funciona.tsx`
  es asimétrica).

## Elevation & Depth

Plano por defecto: la separación la hacen el borde y el cambio de superficie.
La sombra dice «esto flota», así que solo la llevan las capas que flotan, y
siempre teñida con `shadow-ink`.

### Shadow Vocabulary

- **Anclada** (`shadow-md`): lo que cuelga de un control (popover, menú,
  select, tooltip, toast, barra de selección).
- **Modal** (`shadow-lg`): diálogo, sheet, paleta de comandos.
- **Interior** (`shadow-sm`): piezas dentro de un control, como el pulgar del
  switch.

### Named Rules

**The Floating Only Rule.** Paneles, tarjetas, botones, campos y badges no
llevan sombra.

## Shapes

Esquinas suaves y contenidas: `rounded-md` (8 px) en controles, chips y badges;
`rounded-xl` (14 px) en paneles; `rounded-full` solo en puntos y avatares. Sin
píldoras ni radios grandes. Bordes finos semitransparentes del mismo tono que
los neutros.

## Components

Antes de escribir una receta a mano, usa el primitivo. En la consola no se usan
`Card`, `EmptyState` ni `KpiCard` (los retira el lint).

### Buttons

- **Shape:** `rounded-md` (8 px).
- **Primary:** fondo `primary`, texto `primary-foreground`; 36 px de alto, y en
  la consola `size="sm"` (28 px desde `md`, `text-tf-meta`).
- **Hover / Focus:** el fondo baja a `/90`; foco con anillo de 2 px en `ring`
  separado del fondo; al pulsar escala a 0,97 (sin escala con reduced-motion).
- **Outline / Ghost / Link:** outline sobre `card` con borde `input`; ghost sin
  fondo hasta el hover en `accent`; link en `primary` subrayado al hover.

### Chips

- **Style:** `Badge`, `rounded-md` con borde fino y tinte `/10` del color
  semántico (`neutral`, `success`, `warning`, `info`, `destructive`).

### Cards / Containers

- **Corner Style:** `rounded-xl` (14 px).
- **Background:** `card` opaco, borde `border/60` (`SUPERFICIE_PANEL`).
- **Shadow Strategy:** ninguna (ver Elevation & Depth).
- **Primitivos:** [console/panel.tsx](web/src/components/console/panel.tsx):
  `Panel`, `PanelTitle`, `SectionTitle`, `Fact`, `PanelTabs`, `Segmented`,
  `EnlaceIr`.

### Inputs / Fields

- **Style:** borde `input`, fondo transparente, `rounded-md`, 36 px de alto.
- **Focus:** anillo de 1 px en `ring`.
- **Estructura:** [ui/field.tsx](web/src/components/ui/field.tsx): `Field` con
  la etiqueta encima, la ayuda debajo y el error debajo de la ayuda
  (`ETIQUETA_CAMPO`, `AYUDA_CAMPO`, `ERROR_CAMPO`).

### Navigation

- **Rail:** icono propio por espacio y, debajo, la palabra completa en
  castellano; unos 72 px de ancho (D3).

### StatStrip

El KPI canónico: `StatCell`/`StatStrip`, cifra a 20 px sans tabular y rótulo
en frase debajo (D7).

### Estados

- **Carga:** `Skeleton`/`PanelLoading` con la forma de lo que va a llegar
  (barrido `tf-shimmer`, quieto con reduced-motion). Los spinners quedan para
  acciones en curso dentro de un botón.
- **Vacío:** `PanelEmpty` con título y pista concretos («Ningún CPV con
  adjudicaciones en el ámbito actual. Amplía las fechas.»), no «Sin datos».
- **Error:** `PanelError` en línea con «Detalle técnico» plegado y Reintentar;
  un solo aviso por fallo (lo que se pinta en línea no lanza además un toast).
- **Avisos:** `Aviso` (`components/console/aviso.tsx`) para las bandas info,
  warning, danger y success.

### Iconos

Solo lucide, a `h-3`, `h-3.5` o `h-4`; un icono, un concepto
([lib/iconos.ts](web/src/lib/iconos.ts)). Sin emojis ni Sparkles (D5).

## Do's and Don'ts

### Do:

- **Do** usa los tokens semánticos (`bg-card`, `text-muted-foreground`) y la
  escala `text-tf-*`.
- **Do** transiciona color, fondo y borde en los cambios de estado, a 150 ms por
  defecto y ≤ 200 ms en la UI operativa, con las curvas propias (`--ease-out`,
  `--ease-in-out`, `--ease-drawer`).
- **Do** mueve solo con `transform` y `opacity`, y respeta
  `prefers-reduced-motion` conservando los fundidos de opacidad y color.
- **Do** pinta las cifras, las barras de puntuación y las de progreso en su
  valor.

### Don't:

- **Don't** animes lo que se usa cien veces al día (teclado, navegación, cambio
  de pestaña) ni los datos que el usuario vino a leer.
- **Don't** uses `translate` en hover, pulsos infinitos decorativos ni Framer
  Motion: los enter/exit son los primitivos CSS de `globals.css`.
- **Don't** pongas sombra a lo que vive en la página, ni cristal, grano, mallas
  de degradado o negro puro.
- **Don't** escribas `text-[Npx]` ni uses la paleta cruda de Tailwind.

## Skills de diseño: cuál usar y qué no aplica

Las skills viven en `.claude/skills/` (Claude Code) y en su copia
`.agents/skills/` (resto de herramientas); el inventario está en
[docs/skills-inventory.md](docs/skills-inventory.md). Son heurísticas
generales: donde chocan con una decisión registrada, manda la decisión.

Las de estética general **no se invocan solas** (`disable-model-invocation:
true`): `frontend-design`, `design-taste-frontend`, `minimalist-ui` y
`redesign-existing-projects` piden un rumbo visual propio (maximalismo, grano,
Motion, una fuente distinta en cada página) que contradice este fichero si se
aplica a la consola. Se piden por nombre y para la portada.

`impeccable` sí se invoca sola y lee este fichero y [PRODUCT.md](PRODUCT.md)
antes de tocar nada; su regla «el brief manda» hace que respete lo de aquí. Su
instalador compila una variante por herramienta (`.claude`, `.agents`,
`.github`, `.opencode`), así que es la excepción a la copia idéntica (ver
`harnessVariants` en `skills-lock.json`).

| Tarea | Skill | Cómo se carga |
|---|---|---|
| Pantalla o componente de la consola | Este fichero y las reglas de la casa de [docs/UX_AUDIT.md](docs/UX_AUDIT.md); `impeccable` para criticar, auditar o pulir sin salirse de ellos | Sola |
| Añadir o cambiar una animación | `emil-design-eng`, `apple-design` y [docs/frontend-motion.md](docs/frontend-motion.md) | Solas |
| Revisar un diff con movimiento | `review-animations` | Por nombre |
| Buscar dónde falta movimiento, o auditar el que hay | `find-animation-opportunities` / `improve-animations` | Sola / por nombre |
| Ponerle nombre a un efecto | `animation-vocabulary` | Sola |
| Elegir una librería | `pick-ui-library`, contrastada con `web/package.json` (no reintroduce `motion` ni añade NumberFlow) | Por nombre |
| Accesibilidad y revisión de interfaz | `accessibility`, `web-design-guidelines` (fijada a un commit; lo que choque con este fichero se reporta como conflicto) | Solas |
| Rendimiento de React/Next y API de componentes | `vercel-react-best-practices` (con TanStack Query, no SWR), `vercel-composition-patterns` | Solas |
| Rediseño o pulido de la portada | `design-taste-frontend` (sus scripts lanzan Chrome y descargan imágenes), `frontend-design`, `minimalist-ui`, `redesign-existing-projects` | Por nombre |
| SEO de la portada | `seo` (genérica; la de verdad es la Metadata API de Next) | Por nombre |

`full-output-enforcement` no es de diseño y tampoco se invoca sola
(`disable-model-invocation`): pedila por nombre cuando haga falta una entrega
completa, sin placeholders.

El 2026-10-18 se retiraron once skills tras contrastarlas con este fichero:

- `design-taste-frontend-v1` y `-v2-experimental`: versiones antiguas que se
  conservaban solo por compatibilidad.
- `gpt-taste` y `high-end-visual-design`: GSAP obligatorio, un RNG de Python
  simulado y una estética opuesta a la casa.
- `stitch-design-taste` (Google Stitch) e `industrial-brutalist-ui`, que se
  activaba con «data-heavy dashboards».
- `brandkit`, `image-to-code`, `imagegen-frontend-web` e
  `imagegen-frontend-mobile`: exigen generar imágenes, una herramienta que aquí
  no hay, y no existe app móvil.
- `ui-ux-pro-max`: sus `data/` y `scripts/` eran enlaces rotos y ordenaba
  ejecutar un `search.py` inexistente.

Antes de reinstalar alguna, mirá por qué salió.

| Regla de la skill | En TenderFlow |
|---|---|
| Serif prohibida en dashboards, o «serif display como atajo a premium» (`design-taste-frontend`) | **No aplica**: Fraunces en titulares ≥ 15 px es la decisión D1 |
| Lucide prohibido; Phosphor o Radix Icons (`minimalist-ui`, `redesign-existing-projects`) | **No aplica**: lucide en todo el árbol |
| Motion o GSAP, reveals de 500-900 ms al hacer scroll, stagger en listas, bucles infinitos, parallax (`frontend-design`, `design-taste-frontend`, `minimalist-ui`, `redesign-existing-projects`) | **No aplica**: `docs/frontend-motion.md` los excluye; el stagger solo va en el hero de la portada |
| Transiciones de 200-300 ms en todo lo interactivo | **No aplica**: 150 ms por defecto, ≤ 200 ms en la consola |
| Padding generoso (`py-24` o más), píldoras, radios grandes | **No aplica**: la consola es densa; `rounded-md` y `rounded-xl` |
| Grano, ruido, mallas de degradado, cristal, sombras dramáticas, una fuente distinta en cada página (`frontend-design`, `redesign-existing-projects`) | **No aplica**: paneles opacos, D4 y los tokens de `globals.css` |
| Sin `shadow-md`/`shadow-lg` (`minimalist-ui`) | **No aplica**: la sombra va en lo que flota (popover, menú, modal) |
| «Randomize dates to appear real» (`redesign-existing-projects`) | **Nunca**: el frontend no fabrica datos ([docs/frontend-data-invariants.md](docs/frontend-data-invariants.md)) |
| `dvh` en vez de `h-screen` | Aplica |
| Neutros de una sola familia, sin negro puro | Aplica (neutros cálidos, `bg-scrim`) |
| Skeletons en vez de spinners para contenido; estados vacío, error y carga | Aplica (ver «Estados» en Components) |
| Sin filas de tres columnas iguales en la portada | Aplica (`landing-como-funciona.tsx`, asimétrica) |
| Mover solo con `transform`/`opacity` | Aplica al movimiento; color, fondo y borde sí transicionan |
| Cifras tabulares | Aplica (el body activa `tnum`) |
