# Motion en `web/` (design engineering, principios de Emil Kowalski)

Fuente: las 7 skills `emilkowalski/skill` (`skills-lock.json`) — `emil-design-eng`,
`review-animations`, `apple-design`, `find-animation-opportunities`,
`improve-animations`, `pick-ui-library`, `animation-vocabulary`. Este documento
es la referencia rápida de lo que ya está implementado en el repo; para el
catálogo completo de reglas, ver las skills directamente
(`.agents/skills/*/SKILL.md`).

## Tokens

Declarados en `web/src/app/globals.css` dentro de un bloque `@theme` (no
`inline`, para que `@utility animate-in/out` pueda leerlos como custom
properties en CSS plano). Tailwind v4 los expone automáticamente como
utilities `ease-*`, sobrescribiendo las curvas débiles por defecto:

```css
@theme {
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);      /* clase: ease-out */
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);  /* clase: ease-in-out */
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);   /* clase: ease-drawer */
}
```

**Nunca** `ease-in` en UI — arranca lento, retrasa el instante que el usuario
está mirando. `ease-in` solo existe como default débil de Tailwind; no se usa
en ningún componente del repo.

## Duración por tipo de elemento

| Elemento | Duración | Dónde |
| --- | --- | --- |
| Press feedback (`tf-pressable`, `Button` `active:`) | 160ms | `globals.css` |
| Tooltips | 150ms enter (skip en repetición) | `ui/tooltip.tsx` |
| Dropdown / Select / Popover | 150ms | `@utility animate-in/out` |
| Sheet / Dialog | 300ms enter / 200ms exit (asimétrico) | `anim-duration-300`/`-200` |
| Login (rare/first-load) | 200ms | `app/login/page.tsx` |

Regla: **animaciones de UI se quedan bajo 300ms**. El Sheet/Dialog es la
única excepción reconocida (200–500ms es el presupuesto correcto para
modales/drawers) y aun así su *salida* es más rápida que su *entrada* — el
sistema responde rápido, el usuario decide despacio.

## Primitivos de enter/exit (`globals.css`)

`animate-in`/`animate-out` + `fade-in-0`/`zoom-in-95`/`slide-in-from-*`
replican `tailwindcss-animate` sobre `@utility` de Tailwind v4 (custom
properties `--tf-enter-*`/`--tf-exit-*` consumidas por los keyframes
`tf-enter`/`tf-exit`). Todos los overlays Radix del repo (`dropdown-menu`,
`select`, `sheet`, `dialog`, `popover`, `tooltip`) usan este mismo lenguaje,
así que un dropdown y un sheet *sienten* la misma familia de movimiento
aunque la duración/curva difiera.

`tf-stagger` añade delays en cascada (60ms, tope 6 hijos) a los hijos
directos de un contenedor — usado por `components/motion.tsx` (`Stagger`) y
por el formulario de `app/login/page.tsx`. Es CSS puro (no JS): un contenedor
con la clase, hijos con `animate-in fade-in-0 slide-in-from-bottom-2`.

## Qué NO animar (y por qué ya no hay `motion`/Framer Motion en el bundle)

| Regla | Aplicación en el repo |
| --- | --- |
| Nunca animar acciones de teclado (100+/día) | `command-palette.tsx` — sin animación, deliberado |
| Nunca animar navegación (100+/día) | Sin fade de ruta entre páginas; NProgress es el único indicador |
| Nunca animar datos que el usuario vino a leer | `KpiCard` renderiza el valor directo, sin count-up |
| CSS gana a JS bajo carga | `motion`/Framer Motion salió del bundle: `MotionProvider`, `FadeIn`, `PageTransition` y `AnimatedNumber` se eliminaron; `Stagger` se reescribió en CSS puro |

`motion` como dependencia solo se justifica para springs/gestos reales
(drag-to-dismiss, interacciones interrumpibles). Si algún componente futuro
lo necesita genuinamente, `pick-ui-library` sigue recomendando `motion`
(Framer Motion) para ese caso — no hay que reintroducirla para timers o
transiciones predeterminadas.

## Accesibilidad

- `prefers-reduced-motion: reduce` — **no es cero**: transiciones de
  `opacity`/`color`/`background-color`/`border-color` se conservan a 150ms;
  el movimiento (`--tf-enter-translate-*`, `--tf-enter-scale`) se neutraliza
  reescribiendo las mismas custom properties que consumen los keyframes, así
  que cada overlay degrada a un fade puro en vez de teleportar.
- `prefers-reduced-transparency: reduce` y `prefers-contrast: more` —
  `.tf-glass`, `.tf-glass-strong`, `.tf-sidebar-surface` caen a fondo sólido
  (mismo fallback que el `@supports not (backdrop-filter)` existente).
- `hover:` está redefinido globalmente detrás de
  `@media (hover: hover) and (pointer: fine)` — el estado hover nunca se
  activa por un tap en táctil.

## Overlays: primitivos Radix, no hand-rolled

Los 5 overlays que antes reimplementaban Escape/outside-click a mano
(`SavedViewsMenu`, el `PresetMenu` de `GlobalFilterBar`, el menú de usuario y
el drawer móvil de `TopNav`, el modal de `Comparator`) ahora usan
`components/ui/dropdown-menu.tsx`, `popover.tsx`, `sheet.tsx` o el nuevo
`dialog.tsx`. Beneficio, no solo estético: focus trap, scroll lock y una
animación de *salida* real vienen gratis con el primitivo — antes esos
paneles desaparecían de golpe al cerrarse.

- **Popover vs DropdownMenu**: `DropdownMenu` es un `Menu` de Radix (roving
  focus + typeahead entre items) y pelea con un `<input>` de texto dentro.
  Si el contenido tiene un form control, usar `Popover`
  (`components/ui/popover.tsx`); si es una lista de opciones plana, usar
  `DropdownMenu`.
- **Dialog (modal centrado) vs Sheet (panel de borde)**: los modales
  centrados (`Comparator`) usan `components/ui/dialog.tsx`, que **no**
  sobrescribe `transform-origin` — a diferencia de Sheet/DropdownMenu/Popover
  (anclados al trigger), un modal centrado mantiene el origin por defecto
  (apple-design §7 / emil-design-eng: "modals are exempt").

## Tooltip

`components/ui/tooltip.tsx` envuelve `@radix-ui/react-tooltip`.
`TooltipProvider` está montado una vez en `components/providers.tsx` con
`delayDuration={300}` + `skipDelayDuration={300}` — la regla exacta de la
skill: el primer tooltip de un grupo espera el delay completo (evita
activación accidental al mover el puntero por una toolbar), pero los
siguientes abren instantáneos mientras el puntero se mantenga cerca
(`data-state="instant-open"`, sin `animate-in` aplicado — entra sin
transición, tal como pide la skill).

Cualquier componente que use `<Tooltip>` necesita un ancestro
`TooltipProvider` — si un test renderiza el componente de forma aislada
(fuera del árbol de `Providers`), hay que envolverlo explícitamente (ver
`global-filter-bar.test.tsx`, `top-nav.test.tsx`, `kpi-card.test.tsx`).

**Migración de `title=` nativos**: no se hizo de una vez. Se migraron los
controles interactivos icon-only (`PresetMenu` de `GlobalFilterBar`, el
badge de anomalía de `KpiCard`, los toggles de densidad/tema de `TopNav`).
Los `title=` en celdas de tabla y textos truncados informativos (que no son
controles) quedan fuera de esta pasada — ver `IMPROVEMENT_BACKLOG.md`.

## Virtualización

`components/ui/table.tsx` sigue siendo el primitivo para tablas cortas.
Para listas largas (renovaciones, hasta 1000 filas), usar `TableVirtuoso` de
`react-virtuoso` (ver `app/(dashboard)/renovaciones/page.tsx`): compone con
los mismos `TableHead`/`TableBody`/`TableCell`/`TableRow` de
`ui/table.tsx` vía el prop `components`, pero **sin** el `<div
overflow-auto>` que envuelve `Table` normalmente — Virtuoso es dueño del
único contenedor con scroll. Los componentes `Virtuoso*` van a **module
scope** (no recreados en cada render); los datos por-render (el callback de
navegación) se pasan por `context`, no por closure.

## Vocabulario

Para nombrar un efecto sin adivinar el término, `animation-vocabulary` es el
glosario de referencia (*Pop in*, *Stagger*, *Scroll edge effect*,
*Materialize*, *Rubber-banding*, …).

## Cuándo NO animar (recordatorio rápido)

1. ¿Se ve 100+ veces/día? → no animar.
2. ¿Cuál es el propósito (feedback / consistencia espacial / indicar estado /
   evitar un cambio brusco / explicar / delight en primer uso)? Si la
   respuesta es "queda bien", no calif.
3. ¿Entra dentro del presupuesto de duración de la tabla de arriba?
4. ¿La animación ayuda a leer el dato, o compite con él? Sobre datos que el
   usuario vino a leer, ninguna animación gana a ninguna animación.
