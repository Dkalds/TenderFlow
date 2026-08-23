import { SITE_URL } from "@/lib/site";

/**
 * Datos estructurados de las páginas públicas.
 *
 * Nota honesta sobre el alcance: **schema.org no tiene un tipo para
 * licitaciones**. No se inventa uno ni se fuerza `Product` u `Offer`, que es la
 * tentación habitual — marcar un contrato público como producto en venta es
 * incorrecto y Google lo trata como spam de datos estructurados. Lo que sí
 * aporta valor real aquí son las migas de pan, que Google sí muestra en el
 * resultado de búsqueda, y `ItemList` en los hubs.
 */

export interface Miga {
  nombre: string;
  ruta: string;
}

/**
 * `BreadcrumbList` a partir de las migas visibles en la página.
 *
 * Las rutas se absolutizan contra `SITE_URL`: Google exige URLs absolutas en
 * `item`, y una relativa hace que descarte el bloque entero en silencio.
 */
export function migasJsonLd(migas: Miga[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: migas.map((miga, indice) => ({
      "@type": "ListItem",
      position: indice + 1,
      name: miga.nombre,
      item: `${SITE_URL}${miga.ruta}`,
    })),
  };
}

/** `ItemList` para un hub. `urls` ya deben ser rutas del sitio. */
export function listaJsonLd(nombre: string, entradas: { titulo: string; ruta: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: nombre,
    numberOfItems: entradas.length,
    itemListElement: entradas.map((entrada, indice) => ({
      "@type": "ListItem",
      position: indice + 1,
      name: entrada.titulo,
      url: `${SITE_URL}${entrada.ruta}`,
    })),
  };
}

/**
 * Serializa un bloque de datos estructurados para `dangerouslySetInnerHTML`.
 *
 * Un `<script type="application/ld+json">` es un bloque de datos: el navegador
 * no lo ejecuta. Lo que sí hace es **cerrarlo en cuanto encuentra la secuencia
 * `</script`**, en cualquier parte del texto y sin importar que esté dentro de
 * una cadena JSON. Un título de expediente que contuviera esa secuencia
 * cerraría el bloque de datos y todo lo que viniera detrás pasaría a ser HTML
 * del documento — incluido un `<script>` ejecutable.
 *
 * El contenido de estas páginas viene del backend propio (títulos de PLACSP y
 * TED, nombres de órganos) y React escapa todo lo demás, pero este punto es
 * precisamente el que se salta ese escape. Importa más desde que la superficie
 * prerenderizada se sirve con `'unsafe-inline'` (ver `src/proxy.ts`): ahí la
 * CSP ya no es la segunda línea de defensa, así que la garantía tiene que
 * estar aquí.
 *
 * Se escapa `<` como `\u003c`, que dentro de una cadena JSON es el mismo
 * carácter y ya no forma `</script`. De paso van U+2028/U+2029, legales en JSON
 * pero saltos de línea para el parser de JavaScript.
 */
export function serializarJsonLd(datos: unknown): string {
  return JSON.stringify(datos)
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}
