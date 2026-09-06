import { EMPTY, formatDate } from "@/lib/utils";

/**
 * Fecha de la ficha pública, o `null` si la fuente no la publica.
 *
 * `formatDate` devuelve el guion largo (`EMPTY`) cuando no hay dato, que es lo
 * correcto dentro de una tabla —la celda existe y está vacía— y equivocado en
 * la ficha: aquí la ausencia se resuelve **no pintando** la fila ni el
 * destacado, en vez de dejar una etiqueta con un guion al lado. Devolviendo
 * `null` la decisión la toma quien pinta, que es el único que sabe si su hueco
 * puede desaparecer.
 *
 * La comparten los datos del anuncio y el bloque de atribución legal, que es la
 * razón de que viva en su propio módulo y no dentro de uno de los dos.
 */
export function fechaOpcional(valor: string | null | undefined): string | null {
  const formateada = formatDate(valor);
  return formateada === EMPTY ? null : formateada;
}
