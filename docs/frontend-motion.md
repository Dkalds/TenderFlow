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
  --default-transition-duration: 150ms;               /* cualquier transition-* sin duration-* */
  --default-transition-timing-function: var(--ease-out); /* ...y sin ease-* */
}
```

Las dos últimas líneas son el valor por defecto de cualquier `transition-*`
que no fije duración ni curva. Hasta el 2026-09-26 no existían, y la mitad de
los `transition-colors` del árbol (los que van sin `duration-*` ni `ease-*`)
usaban la curva estándar de Tailwind, justo la débil que este bloque sustituye.

**Nunca** `ease-in` en UI — arranca lento, retrasa el instante que el usuario
está mirando. `ease-in` solo existe como default débil de Tailwind; no se usa
en ningún componente del repo.

**`scale-*` y `translate-*` no son `transform` en Tailwind v4.** Escriben las
propiedades CSS `scale` y `translate`, así que una lista
`transition-[transform,…]` no las anima y la pulsación salta sin transición.
En `transition-[…]` se nombran (`transition-[scale,background-color]`,
`transition-[translate,color]`) o se usa `transition-transform`, que ya las
incluye. Había 23; hoy una lista con `transform` no pasa `npm run lint`
(`restriccionesDeAspecto` en `web/eslint.config.mjs`).

## Duración por tipo de elemento

| Elemento | Duración | Dónde |
| --- | --- | --- |
| Hover y cambio de estado (color, borde, fondo) | 150ms, curva de la casa (por defecto) | `@theme` de `globals.css` |
| Filas de tabla y de lista (hover) | 110ms, solo color | `ui/table.tsx` y filas propias |
| Fila activa del Radar al moverse con J/K | instantánea: la transición de color va solo en `hover:` | `radar-fila.tsx` |
| Pulsación de controles (`tf-pressable`, `Button` `active:`) | 150ms, `scale: 0.97` | `globals.css`, `ui/button.tsx` |
| Pulsación de superficies grandes (filas enlazadas, celdas de la tira de KPIs, tarjetas enlace) | tinte instantáneo: `active:bg-primary/10 active:duration-0`, sin escala | `PULSABLE_SOBRE_TARJETA` de `console/panel.tsx` y filas propias |
| Tooltips | 150ms enter (skip en repetición) | `ui/tooltip.tsx` |
| Dropdown / Select / Popover | 150ms | `@utility animate-in/out` |
| Sheet / Dialog | 300ms enter / 200ms exit (asimétrico) | `anim-duration-300`/`-200` |
| Puerta (login, restablecer, 404): una sola entrada del contenido, la del panel | 200ms | `(publico)/_components/puerta.tsx` |
| Fondo de `/login`: fundido de entrada, una vez por visita | 500ms | `login/_components/fondo-particulas.tsx` |
| Esqueleto de carga (`Skeleton`, `.tf-shimmer`) | barrido de 1,2 s, `linear` | `globals.css` |

Regla: **animaciones de UI se quedan bajo 300ms** (bajo 200ms en la UI
operativa de la consola). El Sheet/Dialog es la única excepción reconocida
(200–500ms es el presupuesto correcto para modales/drawers) y aun así su
*salida* es más rápida que su *entrada* — el sistema responde rápido, el
usuario decide despacio.

`tf-pressable` es una clase sin capa, no una `@utility`: casi siempre va junto
a `transition-colors`, y como utilidades las dos escribían `transition-property`
y la de colores ganaba, así que la escala saltaba. Ahora declara ella misma los
colores y la escala, y toma la duración y la curva de `duration-*`/`ease-*` si
el elemento las trae. Las tarjetas enlace grandes de la portada usan 0,99 en
vez de 0,97: a ese tamaño, 0,97 se ve como un salto.

Un barrido continuo (el del esqueleto, una barra de progreso) va en `linear`:
la curva por defecto, `ease`, lo hace acelerar y frenar en cada pasada. Es el
único lenguaje de carga: nada de `animate-pulse` suelto ni un icono que late al
lado de las líneas de esqueleto.

## Primitivos de enter/exit (`globals.css`)

`animate-in`/`animate-out` + `fade-in-0`/`zoom-in-95`/`slide-in-from-*`
replican `tailwindcss-animate` sobre `@utility` de Tailwind v4 (custom
properties `--tf-enter-*`/`--tf-exit-*` consumidas por los keyframes
`tf-enter`/`tf-exit`). Todos los overlays Radix del repo (`dropdown-menu`,
`select`, `sheet`, `dialog`, `popover`, `tooltip`) usan este mismo lenguaje,
así que un dropdown y un sheet *sienten* la misma familia de movimiento
aunque la duración/curva difiera.

`tf-stagger` añade delays en cascada (60ms, tope 6 hijos) a los hijos
directos de un contenedor. Es CSS puro (no JS): un contenedor con la clase,
hijos con `animate-in fade-in-0 slide-in-from-bottom-2`. Solo para lo que se
ve una vez por visita: el hero de la portada
(`(publico)/_components/landing-hero.tsx`). **No se usa en el dashboard**:
escalonar KPIs, tarjetas o filas que se consultan a diario anima justo el dato
que se vino a leer. El componente `Stagger` (`components/motion.tsx`) se retiró
el 2026-09-26 con su único consumidor, la tira de KPIs de Competencia.

## Qué NO animar (y por qué ya no hay `motion`/Framer Motion en el bundle)

| Regla | Aplicación en el repo |
| --- | --- |
| Nunca animar acciones de teclado (100+/día) | `command-palette.tsx` — sin animación, deliberado. Y J/K en el Radar: la fila activa cambia de color al instante y sus acciones no vuelven a entrar deslizándose en cada tecla, como hacían hasta el 2026-09-26 |
| Nunca animar navegación (100+/día) | Sin fade de ruta entre páginas y sin barra de progreso: la navegación la señalan los `loading.tsx` de cada segmento, que pintan al instante. NProgress se retiró el 2026-09-26: solo se encendía con clics en `<a>`, así que las navegaciones por `router.push` (paleta ⌘K, atajos G+X, Agenda, Renovaciones) no daban ninguna señal, y su «peg» luminoso era la firma del ejemplo `with-nprogress` |
| Nunca animar datos que el usuario vino a leer | `StatCell` pinta el valor directo, sin count-up ni entrada escalonada. Las barras de puntuación y de plazo, igual: el ancho se pinta sin transición. Con los 420 ms que llevaban no llegaban a verse en cuatro sitios, y en la ficha de /detalle interpolaban la puntuación de una licitación hasta la de la siguiente |
| Cambio de pestaña | `PanelTabs` y `TabsContent` cambian el contenido al instante: se cambian con flechas (teclado) y muchas veces por sesión |
| Hover en la consola: solo color u opacidad | Filas, celdas, tarjetas y enlaces «ir a» (`EnlaceIr`) no se desplazan al pasar el ratón: lo que se ve decenas de veces al día no se mueve. Sin `translate` de hover ni `animate-ping`/pulsos infinitos decorativos (`animate-ping` y `animate-bounce` no pasan el lint). El único parpadeo que queda es el cursor mientras se emite una respuesta del chat, `motion-safe` y `aria-hidden` |
| Nada de fondos animados a pantalla completa, con una excepción: `/login` | El login tuvo una red de partículas en canvas (un bucle `requestAnimationFrame` perpetuo) sobre una retícula con máscara; se retiraron el 2026-09-26 (apple-design §14; WCAG 2.2.2). La red volvió el 2026-10-04 por decisión del dueño, solo a `/login` y sin la retícula (`login/_components/fondo-particulas.tsx`, `login/_lib/red-particulas.ts`), con lo que le faltaba: un botón que la pausa, un solo fotograma con `prefers-reduced-motion`, bucle parado con la pestaña oculta y paso medido en tiempo (misma velocidad a 60 que a 120 Hz). El formulario va en un panel sólido que la tapa. No es precedente para la consola ni para la portada |
| CSS gana a JS bajo carga | `motion`/Framer Motion salió del bundle: `MotionProvider`, `FadeIn`, `PageTransition` y `AnimatedNumber` se eliminaron; `Stagger` se reescribió en CSS puro y después se retiró |

`motion` como dependencia solo se justifica para springs/gestos reales
(drag-to-dismiss, interacciones interrumpibles). Si algún componente futuro
lo necesita genuinamente, `pick-ui-library` sigue recomendando `motion`
(Framer Motion) para ese caso — no hay que reintroducirla para timers o
transiciones predeterminadas.

## Toasts

`components/toaster.tsx` envuelve Sonner **sin `richColors`**: la caja es una
capa flotante de la consola (`--card`, borde, sombra md, la sans de la app) y
el tipo lo dicen la forma y el color del icono de contorno. Las variables de
Sonner (`--normal-bg`, `--normal-border`, `--normal-text`) se redefinen desde
los tokens en `globals.css`, con `html` delante del selector: la hoja de Sonner
se inyecta sin capa en tiempo de ejecución, así que ni sus valores por defecto
ni las clases de `toastOptions.classNames` (utilidades con capa) valen para
esto. El movimiento es el de Sonner, que ya respeta reduced-motion.

## Accesibilidad

- `prefers-reduced-motion: reduce` — **no es cero**: transiciones de
  `opacity`/`color`/`background-color`/`border-color` se conservan a 150ms;
  el movimiento (`--tf-enter-translate-*`, `--tf-enter-scale`) se neutraliza
  reescribiendo las mismas custom properties que consumen los keyframes, así
  que cada overlay degrada a un fade puro en vez de teleportar.
- `prefers-reduced-transparency: reduce` y `prefers-contrast: more` —
  `.tf-glass` y `.tf-glass-strong` caen a fondo sólido (mismo fallback que el
  `@supports not (backdrop-filter)` existente). El vidrio solo se usa donde de
  verdad pasa contenido por debajo: la cabecera pública sticky y las capas
  flotantes no modales; un modal va en `bg-popover` sólido.
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
`empresas/__tests__/maestro-list.test.tsx` o
`mercado/_components/__tests__/renovaciones-view.test.tsx`).

**Migración de `title=` nativos**: cerrada el 2026-09-18 (techo 0 en
`scripts/check_title_attrs.py`, `deudaTitleNativo` vacía). Dos herramientas:

- **Controles** (ya focusables): `<Tooltip>` con `TooltipTrigger asChild`.
  No añade paradas de tabulación y se abre también con foco.
- **Texto truncado, celdas y casillas de heatmap**: `<Pista>`
  (`components/ui/pista.tsx`). El disparador es el propio elemento y **no** es
  focusable, para que una tabla de 25 filas o un heatmap de 365 casillas no
  gane una parada de tabulación por celda. Lo que el teclado y el lector
  necesitan va en el texto: el recorte es CSS (el DOM guarda la cadena
  entera), y lo que solo estaba en el `title` pasa a `sr-only` o a
  `role="img"` + `aria-label` en las casillas sin texto.

## Virtualización

`components/ui/table.tsx` sigue siendo el primitivo para tablas cortas.
Para listas largas (renovaciones, hasta 1000 filas), usar `TableVirtuoso` de
`react-virtuoso` (ver
`app/(dashboard)/mercado/_components/renovaciones/renovaciones-lista.tsx`): compone con
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
