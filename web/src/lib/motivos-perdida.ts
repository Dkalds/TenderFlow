/**
 * F3.1 — motivos de pérdida codificados (D37).
 *
 * La lista es **cerrada** a propósito: una lista abierta no se puede agregar,
 * y el reparto «perdemos por precio en el 60 % de los casos» es justo lo que
 * esta pieza existe para poder decir. El orden y los códigos salen del
 * contrato (`PursuitUpdate.outcome_reason_code`): un código que el backend
 * retire o renombre deja de compilar aquí.
 *
 * `sin_codificar` **no** es un motivo: es la etiqueta con la que el backend
 * cuenta los cierres anteriores a F3.1. Tiene etiqueta legible porque aparece
 * en el reparto, pero no se ofrece en el selector.
 */
import type { PursuitMetrics, PursuitUpdate } from "@/lib/api-types";

export type MotivoPerdida = NonNullable<PursuitUpdate["outcome_reason_code"]>;

export const MOTIVOS_PERDIDA = [
  { codigo: "precio", etiqueta: "Precio", ayuda: "Otra oferta fue más barata." },
  { codigo: "tecnica", etiqueta: "Oferta técnica", ayuda: "Perdimos en los criterios de valor." },
  { codigo: "solvencia", etiqueta: "Solvencia", ayuda: "No acreditamos la solvencia exigida." },
  { codigo: "plazo", etiqueta: "Plazo", ayuda: "No llegamos a presentar a tiempo o completo." },
  {
    codigo: "desierto_o_anulado",
    etiqueta: "Desierto o anulado",
    ayuda: "El órgano no adjudicó a nadie.",
  },
  { codigo: "no_presentada", etiqueta: "No presentada", ayuda: "Decidimos no presentar al final." },
  { codigo: "otro", etiqueta: "Otro", ayuda: "Explica el motivo en la nota de cierre." },
] as const satisfies ReadonlyArray<{ codigo: MotivoPerdida; etiqueta: string; ayuda: string }>;

/** Etiqueta de los cierres anteriores a F3.1 en el reparto. */
export const SIN_CODIFICAR = "sin_codificar";

/** Texto legible de un motivo, incluido `sin_codificar`; el código crudo si es desconocido. */
export function etiquetaMotivo(codigo: string): string {
  if (codigo === SIN_CODIFICAR) return "Sin codificar";
  return MOTIVOS_PERDIDA.find((motivo) => motivo.codigo === codigo)?.etiqueta ?? codigo;
}

export function esMotivoPerdida(valor: string): valor is MotivoPerdida {
  return MOTIVOS_PERDIDA.some((motivo) => motivo.codigo === valor);
}

/**
 * Error de validación del cierre, o `null` si se puede guardar.
 *
 * Replica en cliente la regla del backend (`lost` sin código → 422) para que
 * el aviso llegue antes de pulsar Guardar, y añade la de D37 que el backend no
 * comprueba: «otro» va **con texto**, porque un «otro» sin explicación es un
 * cierre sin motivo con otra etiqueta.
 */
export function errorDeCierre(
  outcome: string,
  codigo: string | null | undefined,
  nota: string,
): string | null {
  if (outcome !== "lost") return null;
  if (!codigo) return "Elige el motivo de la pérdida: es obligatorio al cerrar como perdida.";
  if (codigo === "otro" && !nota.trim()) {
    return "Con «Otro», explica el motivo en la nota de cierre.";
  }
  return null;
}

/**
 * Cierre anterior a F3.1 que se puede completar: perdida y sin código. La UI
 * lo ofrece en vez de dejarlo contado para siempre como `sin_codificar`.
 */
export function pideCodificar(pursuit: {
  outcome: string;
  outcome_reason_code?: string | null;
}): boolean {
  return pursuit.outcome === "lost" && !pursuit.outcome_reason_code;
}

export type RepartoPerdidas =
  | { estado: "publicable"; filas: NonNullable<PursuitMetrics["perdidas_por_motivo"]> }
  | { estado: "insuficiente"; perdidas: number; minimo: number };

/**
 * El reparto tal como se puede pintar. El mínimo lo aplica el backend —por
 * debajo devuelve la lista vacía—; aquí sólo se distingue «vacío porque no
 * llega» de «hay reparto», para decir cuántas faltan en vez de un hueco mudo.
 */
export function repartoPerdidas(metrics: PursuitMetrics): RepartoPerdidas {
  const filas = metrics.perdidas_por_motivo ?? [];
  if (filas.length > 0) return { estado: "publicable", filas };
  return {
    estado: "insuficiente",
    perdidas: metrics.pursuits_lost,
    minimo: metrics.perdidas_n_minimo,
  };
}
