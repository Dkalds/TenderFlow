/**
 * Triaje desde el resumen diario: el correo enlaza a la ficha con
 * `?lic=<id>&desde=resumen&intencion=interesa|descartar`
 * (`services/email_digest.py::enlaces_de_triaje`) y la ficha ofrece la acción.
 *
 * El enlace no actúa solo, a propósito: un escáner de correo que visite la URL
 * no puede crear ni descartar nada, porque la acción la confirma con un botón
 * quien tiene la sesión abierta.
 */

/** Parámetros de la URL que trae el enlace del correo. */
export const PARAMETRO_DESDE = "desde";
export const PARAMETRO_INTENCION = "intencion";

/** Valor de `desde` que pone el correo (`ORIGEN_RESUMEN` en el backend). */
export const ORIGEN_RESUMEN = "resumen";

export type IntencionTriaje = "interesa" | "descartar";

/**
 * La intención del enlace, o `null` si la URL no viene del resumen o trae
 * otra cosa. Un valor desconocido no se adivina: sin intención no hay franja.
 */
export function intencionDeTriaje(desde: string | null, intencion: string | null): IntencionTriaje | null {
  if (desde !== ORIGEN_RESUMEN) return null;
  return intencion === "interesa" || intencion === "descartar" ? intencion : null;
}
