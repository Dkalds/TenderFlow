/**
 * Piel propia de la portada: las clases que aparecen en más de un bloque de la
 * landing y en ningún otro sitio.
 *
 * Vive aparte porque los bloques de la landing se repartieron en ficheros
 * (`landing-hero`, `landing-como-funciona`, `landing-secciones`, …) y estas
 * cadenas son justo lo que **no** puede divergir entre ellos. Lo que comparte
 * la portada con el resto de la superficie pública —el rótulo de sección, los
 * CTA, el titular de página— se mudó a `piel-publica.ts` (auditoría F46): el
 * rótulo de la portada y el de los hubs eran dos recetas distintas. Una clase
 * que solo usa un bloque se queda en su bloque.
 */

/* Enlace de "Explorar". Ya no es una tarjeta con borde y sombra: la sección
 * entera pasó a filete, así que aquí basta con la fila y su flecha. Al pasar el
 * ratón cambia el color del filete, nada se desplaza. */
export const FILA_EXPLORAR =
  "group flex items-baseline justify-between gap-4 border-b border-border/50 py-5 " +
  "transition-colors hover:border-primary/50 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* Entrada del hero: única animación de la página (frecuencia "rara" — una vez
 * por visita — y propósito de delight, el caso que la skill permite). Cadencia
 * de 60ms vía `tf-stagger` en el contenedor; el resto de la página se pinta
 * quieta y legible desde el primer frame. */
export const ENTRADA_HERO = "animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-500";
