"use client";

import { useMemo } from "react";
import { useFilterParams, useFilters } from "@/lib/filters";

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

/** Los cuatro que `/analytics/resumen/hoy` sí declara. */
const APLICADOS = ["fecha_desde", "fecha_hasta", "ccaa", "tecnologia"] as const;

/**
 * El trozo del ámbito que `/analytics/resumen/hoy` aplica de verdad.
 *
 * Sirve para pedir a **otro** endpoint el mismo universo que contó ese: la
 * lista de «Vencen en 48 horas» sale de `GET /licitaciones`, que sí acepta los
 * siete filtros, así que mandarle el ámbito entero la dejaría más estrecha que
 * el número que la encabeza — un contador de 37 sobre una lista que sólo puede
 * enseñar los 4 que sobreviven al chip de estado. Recortando aquí, lista y
 * número miden lo mismo y el desajuste que queda es **uno solo**, el que
 * `useFiltrosIgnorados` ya declara para toda la banda.
 */
export function useFiltrosDeResumen(): Record<string, string> {
  const params = useFilterParams();
  return useMemo(() => {
    const aplicados: Record<string, string> = {};
    for (const clave of APLICADOS) {
      const valor = params[clave];
      if (valor) aplicados[clave] = valor;
    }
    return aplicados;
  }, [params]);
}

/** «búsqueda y estado» / «búsqueda, estado y sólo abiertas». */
export function enumerar(valores: string[]): string {
  if (valores.length <= 1) return valores[0] ?? "";
  return `${valores.slice(0, -1).join(", ")} y ${valores[valores.length - 1]}`;
}
