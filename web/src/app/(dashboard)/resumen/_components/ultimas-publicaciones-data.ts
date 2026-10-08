/**
 * Vocabulario de la tabla «Últimas publicaciones» y sus derivaciones puras.
 *
 * Nada de esto agrega: ordena las filas que ya vinieron de
 * `/analytics/resumen/timeline`, traduce el importe de **una** fila a un ancho
 * de barra y nombra su fecha. Los totales y el tope los declara el endpoint
 * (ADR-014).
 */

import { fuenteOrigen } from "@/lib/fuentes";
import { EMPTY, formatDate, formatHoraMinuto } from "@/lib/utils";
import type { TimelineItem } from "./types";

export type DireccionOrden = "asc" | "desc";

/**
 * Anchos como clases y no como `style`: cada estilo en línea ata `style-src` a
 * `'unsafe-inline'` (scripts/check_inline_styles.py). Cadenas literales, para
 * que el JIT de Tailwind las vea.
 */
export const COLUMNAS: {
  key: keyof TimelineItem;
  label: string;
  ancho?: string;
  align?: "right";
}[] = [
  { key: "titulo", label: "Título" },
  { key: "organo_contratacion", label: "Órgano", ancho: "w-[160px]" },
  { key: "ccaa", label: "CCAA", ancho: "w-[104px]" },
  { key: "tipo_contrato", label: "Tipo", ancho: "w-[96px]" },
  { key: "importe", label: "Importe", ancho: "w-[168px]", align: "right" },
  { key: "fecha_publicacion", label: "Fecha", ancho: "w-[96px]" },
  { key: "estado", label: "Estado", ancho: "w-[112px]" },
  { key: "fuente", label: "Origen", ancho: "w-[88px]" },
];

/** Valor por el que se ordena una celda: el origen, por el nombre que se ve. */
function valorDeOrden(item: TimelineItem, clave: keyof TimelineItem): string | number | null {
  if (clave === "fuente") return fuenteOrigen(item.fuente)?.corta ?? null;
  const valor = item[clave];
  return valor ?? null;
}

/**
 * Copia ordenada de las filas. Las celdas vacías van siempre al final: con un
 * importe sin declarar arriba del todo, «de mayor a menor» empezaba por rayas.
 */
export function ordenarPublicaciones(
  items: readonly TimelineItem[],
  clave: keyof TimelineItem,
  direccion: DireccionOrden,
): TimelineItem[] {
  const signo = direccion === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const izquierda = valorDeOrden(a, clave);
    const derecha = valorDeOrden(b, clave);
    if (izquierda == null && derecha == null) return 0;
    if (izquierda == null) return 1;
    if (derecha == null) return -1;
    if (typeof izquierda === "number" && typeof derecha === "number") {
      return signo * (izquierda - derecha);
    }
    return signo * String(izquierda).localeCompare(String(derecha), "es", { sensitivity: "base" });
  });
}

/** Extremos de la barra de importe, en potencias de diez: de 100 € a 10 M€. */
const LOG_MIN = 2;
const LOG_MAX = 7;

/**
 * Ancho (0–100) de la barra de importe de una fila, en escala logarítmica.
 * Lineal, un contrato de 16 M€ dejaba a los demás en un píxel: el 71 % de lo
 * que se publica no llega a 1.000 €. Con importe, al menos un trazo de 2.
 */
export function anchoImporte(importe: number | null | undefined): number {
  if (importe == null || importe <= 0) return 0;
  const proporcion = (Math.log10(importe) - LOG_MIN) / (LOG_MAX - LOG_MIN);
  return Math.min(100, Math.max(2, proporcion * 100));
}

function mismoDia(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/**
 * La fecha de la fila: «hoy 09:05» y «ayer 17:32» para lo reciente, que es lo
 * que la tabla enseña casi siempre, y la fecha a secas para lo anterior. En la
 * hora del navegador, como el resto de la consola.
 */
export function fechaPublicacionCorta(fecha: string | null | undefined, ahora: Date): string {
  if (!fecha) return EMPTY;
  const d = new Date(fecha);
  if (Number.isNaN(d.getTime())) return EMPTY;
  const hora = formatHoraMinuto(d);
  if (mismoDia(d, ahora)) return `hoy ${hora}`;
  const ayer = new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate() - 1);
  if (mismoDia(d, ayer)) return `ayer ${hora}`;
  return formatDate(d);
}
