/**
 * Piel compartida de la portada: las cuatro clases que aparecen en más de un
 * bloque.
 *
 * Vive aparte porque los bloques de la landing se repartieron en ficheros
 * (`landing-hero`, `landing-como-funciona`, `landing-secciones`, …) y estas
 * cadenas son justo lo que **no** puede divergir entre ellos: si el kicker de
 * una sección se retoca en un fichero y no en los otros, la página deja de
 * leerse como una sola composición. Una clase que solo usa un bloque se queda
 * en su bloque.
 */

/* Los CTA a la solicitud comparten piel en el hero, en el intermedio y en el
 * cierre; una sola constante evita que las copias diverjan en el siguiente
 * retoque. Transición con propiedades explícitas (nunca `transition: all`) y
 * feedback de pulsación en `active:` — emil-design-eng: un botón tiene que
 * sentirse pulsado, y la curva es la `--ease-out` de la casa. */
export const CTA_PRIMARIO =
  "group inline-flex h-11 items-center justify-center gap-2 rounded-md bg-primary px-6 " +
  "text-sm font-semibold text-primary-foreground shadow-md " +
  "transition-[transform,background-color,box-shadow] duration-150 ease-out " +
  "hover:bg-primary/90 active:scale-[0.97] focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 " +
  "focus-visible:ring-offset-background";

export const CTA_SECUNDARIO =
  "inline-flex h-11 items-center justify-center rounded-md border border-input " +
  "bg-background/60 px-6 text-sm font-medium " +
  "transition-[transform,background-color,border-color] duration-150 ease-out " +
  "hover:bg-accent hover:text-accent-foreground active:scale-[0.97] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* Enlace de "Explorar". Ya no es una tarjeta con borde y sombra: la sección
 * entera pasó a filete, así que aquí basta con la fila y su flecha. */
export const FILA_EXPLORAR =
  "group flex items-baseline justify-between gap-4 border-b border-border/50 py-5 " +
  "transition-colors duration-150 ease-out hover:border-primary/40 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* Entrada del hero: única animación de la página (frecuencia "rara" — una vez
 * por visita — y propósito de delight, el caso que la skill permite). Cadencia
 * de 60ms vía `tf-stagger` en el contenedor; el resto de la página se pinta
 * quieta y legible desde el primer frame. */
export const ENTRADA_HERO = "animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-500";

/* Kicker de sección: versalita fina, sin píldora ni icono. El anterior era una
 * cápsula con borde, fondo tintado y un icono dentro — el gesto más reconocible
 * de una plantilla de SaaS. */
export const KICKER = "text-muted-foreground text-xs font-medium tracking-[0.14em] uppercase";
