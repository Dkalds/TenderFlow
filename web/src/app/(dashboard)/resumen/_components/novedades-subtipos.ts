/**
 * Vocabulario de «Desde tu última visita»: cómo se llama cada clase de cambio,
 * con qué icono se dibuja y de qué color va en la barra del reparto.
 *
 * Las claves son el `SubtipoAviso` de `services/avisos.py` más `pursuit`, que
 * es el movimiento del equipo (`services/novedades.py`). Los recuentos llegan
 * hechos en `por_subtipo`; aquí no se cuenta nada.
 *
 * El color sale de la posición en el catálogo, no del recuento: «Documentos
 * nuevos» es del mismo color hoy y mañana aunque cambie cuál pesa más. El cajón
 * `cambio` y cualquier subtipo que el frontend aún no sepa nombrar van en el
 * gris de «Otros» (`chart-8`), como en todos los gráficos de la consola.
 */

import {
  ArrowRightLeft,
  CalendarClock,
  CircleSlash,
  CircleX,
  Euro,
  FilePlus,
  Scale,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { ICONO_ENTIDAD } from "@/lib/iconos";
import { getSeriesColor } from "@/lib/chart-colors";

interface SubtipoNovedad {
  etiqueta: string;
  icono: LucideIcon;
}

/** Índice de `chart-8`, el gris que la consola reserva a «Otros». */
const INDICE_OTROS = 7;

/** En el orden en que reparten los colores de la serie. `cambio` cae en «Otros». */
const CATALOGO: [string, SubtipoNovedad][] = [
  ["documento_nuevo", { etiqueta: "Documentos nuevos", icono: FilePlus }],
  ["plazo_ampliado", { etiqueta: "Plazos ampliados", icono: CalendarClock }],
  ["plazo_acortado", { etiqueta: "Plazos acortados", icono: CalendarClock }],
  ["importe_corregido", { etiqueta: "Importes corregidos", icono: Euro }],
  ["adjudicado", { etiqueta: "Adjudicados", icono: Trophy }],
  ["recurso", { etiqueta: "Recursos resueltos", icono: Scale }],
  ["pursuit", { etiqueta: "Oportunidades del equipo", icono: ICONO_ENTIDAD.oportunidad }],
  ["cambio", { etiqueta: "Otros cambios", icono: ArrowRightLeft }],
  ["anulado", { etiqueta: "Anulados", icono: CircleX }],
  ["desierto", { etiqueta: "Desiertos", icono: CircleSlash }],
];

const POSICION = new Map(CATALOGO.map(([clave], indice) => [clave, indice]));
const DESCONOCIDO: SubtipoNovedad = { etiqueta: "Otro aviso", icono: ArrowRightLeft };

export interface EstiloSubtipo extends SubtipoNovedad {
  color: string;
}

/** Nombre, icono y color de una clase de cambio. */
export function estiloSubtipo(clave: string): EstiloSubtipo {
  const indice = POSICION.get(clave);
  if (indice === undefined) return { ...DESCONOCIDO, color: getSeriesColor(INDICE_OTROS) };
  return { ...CATALOGO[indice][1], color: getSeriesColor(indice) };
}

export interface TramoReparto extends EstiloSubtipo {
  clave: string;
  n: number;
  /** Cambios de los tramos anteriores: dónde empieza este en la barra. */
  inicio: number;
}

/**
 * Los tramos de la barra, en el orden del catálogo (los desconocidos al final)
 * y solo los que tienen algún cambio.
 */
export function repartoPorSubtipo(porSubtipo: Record<string, number> | undefined): TramoReparto[] {
  return Object.entries(porSubtipo ?? {})
    .filter(([, n]) => n > 0)
    .sort(([a], [b]) => (POSICION.get(a) ?? CATALOGO.length) - (POSICION.get(b) ?? CATALOGO.length))
    .reduce<TramoReparto[]>((tramos, [clave, n]) => {
      const previo = tramos.at(-1);
      const inicio = previo ? previo.inicio + previo.n : 0;
      return [...tramos, { clave, n, inicio, ...estiloSubtipo(clave) }];
    }, []);
}
