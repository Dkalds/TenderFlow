/**
 * Ventana de cierre — recorte local de /detalle.
 *
 * No son ámbito global: no las conoce `lib/filters.ts`, no viajan al resto de
 * pantallas ni las pinta la barra de filtros. Son locales de /detalle, como
 * `?lic=`. Existen para que una superficie que cuenta plazos —la tarjeta
 * «Vencen 48h» de /resumen— pueda abrir **exactamente** el subconjunto que
 * cuenta: el ámbito global sólo sabe acotar por fecha de publicación, así que
 * sin esto el enlace abría el catálogo entero y la cifra prometía algo que el
 * listado no cumplía.
 *
 * Los nombres son los del contrato de `GET /licitaciones`
 * (`api/routes/licitaciones.py::list_licitaciones`) para que el deep-link se
 * pase tal cual a la query sin tabla de traducción.
 *
 * Funciones puras, sin `"use client"`: el prefetch en servidor de la pantalla
 * (`_lib/prefetch.ts`) calcula con ellas la misma query que el hook.
 */

const _CIERRE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Params de API del recorte, descartando lo que no sea `YYYY-MM-DD`.
 *
 * El backend responde 422 a un formato inválido, y un 422 vacía la tabla
 * entera: una URL manipulada a mano no debe poder tumbar la pantalla, así que
 * el valor ilegible se ignora aquí igual que lo ignora el repository.
 */
export function cierreParams(desde: string | null, hasta: string | null): Record<string, string> {
  const params: Record<string, string> = {};
  if (desde && _CIERRE_RE.test(desde)) params.cierre_desde = desde;
  if (hasta && _CIERRE_RE.test(hasta)) params.cierre_hasta = hasta;
  return params;
}

/** Texto del chip que declara el recorte activo, o `null` si no hay ninguno. */
export function cierreLabel(params: Record<string, string>): string | null {
  const { cierre_desde: desde, cierre_hasta: hasta } = params;
  if (desde && hasta) return `Cierra ${desde} → ${hasta}`;
  if (hasta) return `Cierra hasta ${hasta}`;
  if (desde) return `Cierra desde ${desde}`;
  return null;
}
