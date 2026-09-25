"use client";

import { useEtiquetas } from "@/hooks/use-etiquetas";
import { usePursuitChecklist } from "@/hooks/use-pursuit-checklist";
import { usePursuitKit } from "@/hooks/use-pursuit-kit";

/**
 * El id de la URL como id de oportunidad, o `null` si no lo parece:
 * `/oportunidades/abc` no precarga nada (el pursuit ya dará su 404).
 */
export function idDeRuta(id: string | undefined): number | null {
  if (!id || !/^\d+$/.test(id)) return null;
  const numero = Number(id);
  return Number.isSafeInteger(numero) && numero > 0 ? numero : null;
}

/**
 * Pide, a la vez que el pursuit, lo que la pestaña Resumen va a necesitar y
 * solo depende del id de la URL y de la organización activa.
 *
 * Era una cascada: `/organizations` → `/pursuits/{id}` → y solo entonces el
 * contraste del pliego, el kit y las etiquetas, porque los componentes que
 * los piden no se montan hasta que llega el pursuit. Aquí se piden con los
 * mismos hooks —las mismas claves—, así que al montarse la pestaña encuentran
 * la respuesta, o la petición en vuelo, y nada se pide dos veces. Cada hook
 * sigue esperando a conocer la organización activa, como el pursuit: el
 * ámbito por organización no cambia.
 *
 * La página lo monta mientras el pursuit carga y mientras se ve «Resumen»: en
 * las otras pestañas nadie enseña esas consultas y no hace falta mantenerlas
 * vivas. Los documentos no pueden adelantarse: se piden por el expediente, que
 * llega con el pursuit.
 */
export function PrecargaFicha({ pursuitId }: { pursuitId: number }) {
  usePursuitChecklist(pursuitId);
  usePursuitKit(pursuitId);
  useEtiquetas();
  return null;
}
