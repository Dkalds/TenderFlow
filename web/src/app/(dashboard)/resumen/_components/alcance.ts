"use client";

import { useFilters } from "@/lib/filters";

/**
 * Qué parte del ámbito aplican de verdad los endpoints del Resumen.
 *
 * `/analytics/overview` acepta los siete filtros del ámbito. `/analytics/
 * resumen/hoy` y `/analytics/resumen/timeline` sólo declaran cuatro
 * (`fecha_desde`, `fecha_hasta`, `ccaa`, `tecnologia`); el resto viaja en la
 * query —`useFilteredQuery` manda el ámbito entero— y FastAPI los descarta sin
 * decir nada. Resultado: con un chip de estado o una búsqueda activa, la fila
 * de «Requiere atención» y el panel de publicaciones contaban **otro universo**
 * que la tira de contexto justo debajo, sin una sola marca en pantalla.
 *
 * No se puede arreglar desde el cliente sin fabricar el filtrado (ADR-014), así
 * que lo que se arregla es el silencio: la pantalla declara qué chips no está
 * aplicando ese panel. El día que los endpoints acepten los siete, este módulo
 * devuelve la lista vacía y el aviso desaparece solo.
 */

/** Etiqueta de cada filtro del ámbito que los endpoints de resumen ignoran. */
const ETIQUETAS = {
  q: "búsqueda",
  estado: "estado",
  importe: "importe mínimo",
  abiertas: "sólo abiertas",
} as const;

/**
 * Filtros activos en el ámbito que el endpoint del panel NO aplica, en
 * castellano y listos para enumerar. Vacío = el panel mide lo que el ámbito
 * dice, y entonces no hay nada que avisar.
 */
export function useFiltrosIgnorados(): string[] {
  const { q, estados, importeMin, soloAbiertas } = useFilters();
  const ignorados: string[] = [];
  if (q.trim()) ignorados.push(ETIQUETAS.q);
  if (estados.length) ignorados.push(ETIQUETAS.estado);
  if (importeMin != null) ignorados.push(ETIQUETAS.importe);
  if (soloAbiertas) ignorados.push(ETIQUETAS.abiertas);
  return ignorados;
}

/** «búsqueda y estado» / «búsqueda, estado y sólo abiertas». */
export function enumerar(valores: string[]): string {
  if (valores.length <= 1) return valores[0] ?? "";
  return `${valores.slice(0, -1).join(", ")} y ${valores[valores.length - 1]}`;
}
