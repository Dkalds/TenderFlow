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
