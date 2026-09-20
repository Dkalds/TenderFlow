/**
 * Bandejas y órdenes del Radar. Viven aparte de `use-radar-consola.ts` para
 * que el hook, que ya es la pieza más larga de la pantalla, no tenga que
 * cargar también con el catálogo; el hook los reexporta.
 */

export const SEGMENTS = [
  { key: "bandeja", label: "Bandeja" },
  // T5. Va justo detrás de la bandeja y no al final: es la otra mitad del
  // Radar —lo que todavía no se puede ofertar— y esconderla tras «Todas» la
  // convertiría en una pestaña que nadie encuentra.
  { key: "proximas", label: "Próximas" },
  { key: "siguiendo", label: "Siguiendo" },
  { key: "descartadas", label: "Descartadas" },
  { key: "todas", label: "Todas" },
] as const;

export const SORTS = [
  { key: "score", label: "Score" },
  { key: "plazo", label: "Plazo" },
  { key: "importe", label: "Importe" },
] as const;

export type SegmentKey = (typeof SEGMENTS)[number]["key"];
export type SortKey = (typeof SORTS)[number]["key"];
