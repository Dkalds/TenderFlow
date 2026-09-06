import { getImageProps } from "next/image";
import { CONTENIDO } from "../_content/landing";
import capturaHero from "../_assets/radar-hero.webp";
import capturaHeroMovil from "../_assets/radar-hero-movil.webp";

/* Captura del producto, con art direction.

   Una consola de escritorio completa reducida a los ~342 px de un móvil es
   ilegible: el texto de la tabla queda por debajo de 2 px. Por eso en pantallas
   estrechas se sirve un recorte del panel de detalle —el score, su banda y el
   desglose de las seis dimensiones—, que es estrecho por naturaleza y cuenta la
   misma historia a un tamaño que se lee.

   Va con `<picture>` y no con dos `<Image>` y clases `hidden`, porque con CSS
   el navegador se descarga las dos variantes; aquí sólo baja la que aplica.
   Las dimensiones se declaran en el `<source>` para que el navegador reserve la
   caja correcta antes de decodificar y no haya salto.

   Ya **no** lleva `priority`: desde que el hero enseña dato y no una foto, el
   LCP es texto y esta imagen está por debajo del fold. Marcarla como prioritaria
   competiría con lo que sí hay que pintar primero. */
const SIZES_ANCHA = "(min-width: 1152px) 1104px, calc(100vw - 3rem)";
const SIZES_ESTRECHA = "calc(100vw - 3rem)";

export function CapturaProducto() {
  const comun = { alt: CONTENIDO.capturaAlt };
  const {
    props: { srcSet: ancha },
  } = getImageProps({ ...comun, src: capturaHero, sizes: SIZES_ANCHA });
  const {
    props: { srcSet: estrecha, ...resto },
  } = getImageProps({ ...comun, src: capturaHeroMovil, sizes: SIZES_ESTRECHA });

  return (
    <picture>
      {/* `sizes` va también en el `<source>`: sin él el navegador asume 100vw y
          se descarga la variante de 3840 px para un hueco de 1104. */}
      <source
        media="(min-width: 640px)"
        srcSet={ancha}
        sizes={SIZES_ANCHA}
        width={capturaHero.width}
        height={capturaHero.height}
      />
      <img {...resto} srcSet={estrecha} alt={CONTENIDO.capturaAlt} loading="lazy" className="h-auto w-full" />
    </picture>
  );
}
