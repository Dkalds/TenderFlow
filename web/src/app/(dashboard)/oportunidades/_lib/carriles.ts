/**
 * Definición de los carriles del tablero y la agrupación por expediente.
 *
 * Salieron de `page.tsx` cuando pasó de 300 líneas y el límite `max-lines`
 * (S7.1 del plan 2026-09 v2) la dejó en rojo. La frontera tiene sentido por sí
 * sola: aquí no hay JSX ni estado, solo la tabla de carriles y una función
 * pura — que además así se puede probar sin montar la pantalla.
 */

import type { Pursuit, PursuitStatus } from "@/hooks/use-pursuits";

export const LANES: { title: string; statuses: PursuitStatus[]; description: string }[] = [
  {
    title: "Por decidir",
    statuses: ["identified", "qualifying", "go_no_go"],
    description: "Identificadas, cualificando o en GO/NO-GO",
  },
  { title: "En preparación", statuses: ["preparing"], description: "Trabajo activo de la oferta" },
  { title: "Presentadas", statuses: ["submitted"], description: "Pendientes de resultado" },
  {
    title: "Cerradas",
    statuses: ["won", "lost", "withdrawn"],
    description: "Ganadas, perdidas o retiradas",
  },
];

export interface GrupoExpediente {
  licitacionId: string;
  titulo: string;
  items: Pursuit[];
}

/**
 * Agrupa las tarjetas de un carril por expediente, conservando el orden en que
 * llegaron: el backend ya ordena por `updated_at`, y reordenar aquí sería
 * fabricar un criterio que el listado no dio.
 */
export function agruparPorExpediente(items: Pursuit[]): GrupoExpediente[] {
  const grupos = new Map<string, GrupoExpediente>();
  for (const item of items) {
    const grupo = grupos.get(item.licitacion_id);
    if (grupo) {
      grupo.items.push(item);
    } else {
      grupos.set(item.licitacion_id, {
        licitacionId: item.licitacion_id,
        titulo: item.tender_title ?? `Licitación ${item.licitacion_id}`,
        items: [item],
      });
    }
  }
  return [...grupos.values()];
}
