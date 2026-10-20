# Sistema de diseño de TenderFlow

Resumen del lenguaje visual de `web/` (Next.js 16, React 19, Tailwind v4,
primitivos Radix e iconos lucide). **Este fichero no es la fuente de verdad**:
cada regla vive en el código o en el documento que la decidió, y aquí solo se
enlaza. Si algo de abajo contradice a su fuente, manda la fuente y este fichero
se corrige en el mismo cambio.

| Tema | Fuente de verdad |
|---|---|
| Tokens de color, sombras, radios, escala tipográfica, curvas | [web/src/app/globals.css](web/src/app/globals.css) |
| Familias tipográficas | [web/src/lib/tipografia.ts](web/src/lib/tipografia.ts) |
| Colores de marca fuera del navegador (OG, manifest, `global-error`) | [web/src/lib/marca.ts](web/src/lib/marca.ts) |
| Reglas de la casa y decisiones del dueño (D1-D8) | [docs/UX_AUDIT.md](docs/UX_AUDIT.md) |
| Movimiento | [docs/frontend-motion.md](docs/frontend-motion.md) |
| Invariantes de datos en el frontend | [docs/frontend-data-invariants.md](docs/frontend-data-invariants.md) |
| Trinquetes de aspecto (`restriccionesDeAspecto`) | [web/eslint.config.mjs](web/eslint.config.mjs) |

## Carácter

Una herramienta de trabajo diario para leer un mercado: consola densa, papel
cálido, un solo acento. La portada pública habla el mismo idioma con más aire y
composición editorial (texto a la izquierda, sin ornamento de fondo). Nada se
mueve si no explica algo.

## Color

Tokens HSL en `:root` (claro) y `.dark`, expuestos a Tailwind como
`bg-background`, `text-foreground`, `border-border`, etc.

- **Neutros cálidos.** Papel `40 22% 96%`, tinta `30 14% 10%`, gris secundario
  `34 8% 34%`; en oscuro, fondo `30 8% 5%` (`#0E0D0C`). Una sola familia de
  gris en todo el producto: nada de pizarra (tono ~200) al lado del papel.
- **Un acento.** Naranja tostado `--primary` (`22 78% 34%` en claro,
  `26 88% 62%` en oscuro). Es «lo que se puede hacer»; no decora.
- **Rampa semántica** (`success`, `warning`, `info`, `destructive`, urgencia,
  bandas de score): luminosidades fijadas por contraste WCAG, no por gusto.
  [contraste-tokens.test.ts](web/src/lib/__tests__/contraste-tokens.test.ts)
  recalcula los ratios leyendo `globals.css`: un token que se aclare de más
  rompe el test.
- **Tintes**: `/5` hover, `/10` seleccionado, `/15` énfasis; nunca más de `/16`
  detrás de texto del mismo color. Nada de la paleta cruda de Tailwind
  (`bg-black`, `text-slate-500`…).
- **Velo de modales**: `bg-scrim` (la tinta de sombra al 50 %), no negro puro.
- **Series de gráficos**: `--chart-1` … `--chart-10`, medidos a 3:1 como objeto
  gráfico.

## Tipografía

| Familia | Papel |
|---|---|
| Geist (`font-sans`) | Todo el texto, cifras incluidas (el body activa `tnum`) |
| Geist Mono (`font-mono`) | Solo identificadores y código: expediente, CPV, ids, claves, `<kbd>` |
| Fraunces (`font-display`) | Solo titulares de 15 px o más (decisión D1) |

Escala de seis pasos, sin `text-[Npx]` (lo bloquea el lint):
`text-tf-micro` 11 · `text-tf-meta` 12 · `text-tf-body` 13 (cuerpo de la
consola) · `text-tf-lede` 15 · `text-tf-title` 20 · `text-tf-hero` 32. La
superficie pública trabaja con `text-sm`/`text-base` y tamaños de titular
propios.

Rótulos de dato en sans, en frase, a 11 px (`ROTULO_DATO`); la versal queda
solo para cabeceras de columna (`CABECERA_COLUMNA`).

## Superficies y forma

- Paneles en `bg-card` opaco con borde (`SUPERFICIE_PANEL`, `rounded-xl`).
- Sombra solo en lo que flota: `shadow-md` para lo anclado a un control
  (popover, menú, tooltip, toast), `shadow-lg` para lo modal. Las sombras usan
  `--shadow-ink`, teñida del mismo tono que los neutros.
- Radios: `rounded-md` en controles, chips y badges; `rounded-xl` en paneles;
  `rounded-full` en puntos y avatares.
- Alturas de pantalla completa en `dvh` (`h-dvh`, `min-h-dvh`), no `h-screen`:
  en iOS Safari `100vh` no descuenta la barra de direcciones.

## Primitivos

Antes de escribir una receta a mano, usa el primitivo:

- [console/panel.tsx](web/src/components/console/panel.tsx): `Panel`,
  `PanelTitle`, `SectionTitle`, `Fact`, `StatCell`/`StatStrip` (el KPI
  canónico), `PanelLoading`, `PanelEmpty`, `PanelError`, `PanelTabs`,
  `Segmented`, `EnlaceIr`.
- [ui/field.tsx](web/src/components/ui/field.tsx): `Field` con la etiqueta
  encima, la ayuda debajo y el error debajo de la ayuda (`ETIQUETA_CAMPO`,
  `AYUDA_CAMPO`, `ERROR_CAMPO`).
- [ui/skeleton.tsx](web/src/components/ui/skeleton.tsx): el único lenguaje de
  carga de contenido (barrido `tf-shimmer`, quieto con reduced-motion). Los
  spinners quedan para acciones en curso dentro de un botón, no para contenido
  que llega.
- `Button` (`size="sm"` en la consola), `Badge`, los overlays Radix de
  `components/ui/` y `Aviso` (`components/console/aviso.tsx`) para las bandas
  info, warning, danger y success.

## Estados

- **Carga**: `Skeleton`/`PanelLoading` con la forma de lo que va a llegar, para
  que la pantalla no salte.
- **Vacío**: `PanelEmpty` con título y pista concretos («Ningún CPV con
  adjudicaciones en el ámbito actual. Amplía las fechas.»), no «Sin datos».
- **Error**: `PanelError` en línea con «Detalle técnico» plegado y Reintentar;
  un solo aviso por fallo (lo que se pinta en línea no lanza además un toast).

## Movimiento

Resumen de [docs/frontend-motion.md](docs/frontend-motion.md):

- Curvas propias (`--ease-out`, `--ease-in-out`, `--ease-drawer`) y 150 ms por
  defecto; ≤ 200 ms en la UI operativa.
- No se anima lo que se usa cien veces al día (teclado, navegación, cambio de
  pestaña) ni los datos que el usuario vino a leer (cifras, barras de
  puntuación y de progreso: se pintan en su valor).
- Hover de filas y celdas solo de color; sin `translate` de hover ni pulsos
  infinitos decorativos.
- Solo se mueve con `transform` y `opacity`, nunca con `width`, `height`, `top`
  o `left`; los cambios de estado sí transicionan color, fondo y borde.
- Sin Framer Motion: los enter/exit son los primitivos CSS de `globals.css`.
- Todo respeta `prefers-reduced-motion`, que no quiere decir cero movimiento:
  se conservan los fundidos de opacidad y color. La red de `/login` se queda en
  un fotograma y tiene botón de pausa.

## Iconos y voz

- Solo lucide, a `h-3`, `h-3.5` o `h-4`; un icono, un concepto
  ([lib/iconos.ts](web/src/lib/iconos.ts)). Sin emojis ni Sparkles.
- Castellano peninsular con tuteo. La interfaz no narra su implementación.

## Skills de diseño: cuál usar y qué no aplica

Las skills viven en `.claude/skills/` (Claude Code) y en su copia idéntica
`.agents/skills/` (resto de herramientas); el inventario está en
[docs/skills-inventory.md](docs/skills-inventory.md). Son heurísticas
generales: donde chocan con una decisión registrada, manda la decisión.

Las de estética general **no se invocan solas** (`disable-model-invocation:
true`): `frontend-design`, `design-taste-frontend`, `minimalist-ui` y
`redesign-existing-projects` piden un rumbo visual propio (maximalismo, grano,
Motion, una fuente distinta en cada página) que contradice este fichero si se
aplica a la consola. Se piden por nombre y para la portada.

| Tarea | Skill | Cómo se carga |
|---|---|---|
| Pantalla o componente de la consola | Ninguna de estética: este fichero y las reglas de la casa de [docs/UX_AUDIT.md](docs/UX_AUDIT.md) | — |
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
| Skeletons en vez de spinners para contenido; estados vacío, error y carga | Aplica (ver «Estados») |
| Sin filas de tres columnas iguales en la portada | Aplica (`landing-como-funciona.tsx`, asimétrica) |
| Mover solo con `transform`/`opacity` | Aplica al movimiento; color, fondo y borde sí transicionan |
| Cifras tabulares | Aplica (el body activa `tnum`) |
