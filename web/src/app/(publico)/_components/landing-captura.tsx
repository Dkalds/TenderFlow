import { getImageProps } from "next/image";
import { CONTENIDO } from "../_content/landing";
import capturaHero from "../_assets/radar-hero.webp";
import capturaHeroClaro from "../_assets/radar-hero-claro.webp";
import capturaHeroMovil from "../_assets/radar-hero-movil.webp";
import capturaHeroMovilClaro from "../_assets/radar-hero-movil-claro.webp";

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
   competiría con lo que sí hay que pintar primero.

   Cada recorte va en los dos temas, elegidos por `prefers-color-scheme`, que es
   lo que sigue la portada (`next-themes` con `defaultTheme="system"`, sin
   selector propio): quien tiene el sistema en claro ya no ve una consola
   oscura. shortcut: quien eligió tema a mano en la consola ve la portada en ese
   tema y la captura en el de su sistema; pasarlo a la clase `dark` si la
   portada llega a tener selector de tema. Las capturas las regenera
   `e2e/capturas-landing.spec.ts`. */
const SIZES_ANCHA = "(min-width: 1152px) 1104px, calc(100vw - 3rem)";
const SIZES_ESTRECHA = "calc(100vw - 3rem)";
const OSCURO = "(prefers-color-scheme: dark)";
const ANCHA = "(min-width: 640px)";

export function CapturaProducto() {
  const comun = { alt: CONTENIDO.capturaAlt };
  const srcSet = (src: typeof capturaHero, sizes: string) =>
    getImageProps({ ...comun, src, sizes }).props.srcSet;
  const {
    props: { srcSet: estrechaClara, ...resto },
  } = getImageProps({ ...comun, src: capturaHeroMovilClaro, sizes: SIZES_ESTRECHA });

  return (
    <picture>
      {/* `sizes` va también en el `<source>`: sin él el navegador asume 100vw y
          se descarga la variante de 3840 px para un hueco de 1104. Gana el
          primer `<source>` que casa, así que van de más a menos específico. */}
      <source
        media={`${ANCHA} and ${OSCURO}`}
        srcSet={srcSet(capturaHero, SIZES_ANCHA)}
        sizes={SIZES_ANCHA}
        width={capturaHero.width}
        height={capturaHero.height}
      />
      <source
        media={ANCHA}
        srcSet={srcSet(capturaHeroClaro, SIZES_ANCHA)}
        sizes={SIZES_ANCHA}
        width={capturaHeroClaro.width}
        height={capturaHeroClaro.height}
      />
      <source
        media={OSCURO}
        srcSet={srcSet(capturaHeroMovil, SIZES_ESTRECHA)}
        sizes={SIZES_ESTRECHA}
        width={capturaHeroMovil.width}
        height={capturaHeroMovil.height}
      />
      <img {...resto} srcSet={estrechaClara} alt={CONTENIDO.capturaAlt} loading="lazy" className="h-auto w-full" />
    </picture>
  );
}
