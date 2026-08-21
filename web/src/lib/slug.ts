import { foldText } from "@/lib/utils";

/**
 * Slugs para las URLs públicas.
 *
 * El slug es la parte de la URL que aporta señal semántica a un buscador. No
 * identifica nada: el expediente lo identifica la referencia opaca que va en
 * su propio segmento (ver `shared/public_ref.py`). Esa separación es
 * deliberada — si el slug fuese el identificador, corregir una errata en un
 * título rompería la URL indexada.
 */

/**
 * Convierte un texto libre en un slug apto para una URL.
 *
 * `NFD` + eliminación de diacríticos: "Contratación" pasa a "contratacion" en
 * vez de a "contrataci-n". Un slug con caracteres percent-encoded es legal
 * pero ilegible en un resultado de búsqueda, y los buscadores premian la URL
 * legible.
 */
export function slugificar(texto: string): string {
  // `foldText` ya hace NFD + quitar diacríticos + minúsculas; duplicarlo aquí
  // solo abriría la puerta a que las dos versiones divergieran.
  return foldText(texto)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
    .replace(/-+$/g, "");
}

/**
 * Slug de una comunidad autónoma, con reserva para las que no tienen valor.
 *
 * `ccaa` es nullable en la base de datos y muchos expedientes llegan sin ella.
 * Sin la reserva, esos anuncios producirían la ruta `/licitaciones//<ref>`, que
 * Next normaliza a otra cosa y deja la página inalcanzable. Con un valor fijo
 * caen todos en el mismo hub, que además es una página legítima: "licitaciones
 * sin comunidad autónoma asignada".
 */
export const CCAA_SIN_ASIGNAR = "sin-comunidad";

export function slugCcaa(ccaa: string | null | undefined): string {
  const limpio = slugificar(ccaa ?? "");
  return limpio || CCAA_SIN_ASIGNAR;
}

/**
 * Ruta canónica de la ficha pública de una licitación.
 *
 * Cuatro segmentos y no tres, y la referencia va **suelta** en el último en vez
 * de pegada al slug con un guion. El motivo es que el alfabeto base64url
 * incluye `-` y `_`: con `slug-ref` no habría forma fiable de saber dónde
 * acaba uno y empieza la otra, porque partir por el último guion cortaría en
 * medio de la referencia siempre que ésta contuviera uno.
 */
export function rutaLicitacion(params: {
  ccaa: string | null | undefined;
  titulo: string;
  ref: string;
}): string {
  const slug = slugificar(params.titulo) || "licitacion";
  return `/licitaciones/${slugCcaa(params.ccaa)}/${slug}/${params.ref}`;
}

/** Ruta del hub de una comunidad autónoma. */
export function rutaHubCcaa(ccaa: string | null | undefined): string {
  return `/licitaciones/${slugCcaa(ccaa)}`;
}

/** Ruta del hub de una familia CPV (los dos primeros dígitos). */
export function rutaHubCpv(cpv: string): string {
  return `/cpv/${cpv.replace(/\D/g, "").slice(0, 8)}`;
}
