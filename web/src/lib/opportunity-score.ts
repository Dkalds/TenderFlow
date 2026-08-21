/**
 * Score de oportunidad para renovaciones de contratos.
 *
 * El valor de una renovación no es solo su importe: un contrato grande que el
 * adjudicatario actual renovará casi seguro (riesgo de cambio bajo) no es una
 * oportunidad. Lo accionable combina **riesgo de cambio** (modelo de retención),
 * **importe** y **urgencia** (proximidad del vencimiento).
 *
 * **Este módulo ya no ordena la tabla.** El orden lo decide el SQL
 * (`db/repositories/renovaciones.py`, `order_by=score`) para que un `LIMIT N`
 * devuelva el top-N real del dataset y no el top-N del sample que cupo en el
 * cliente. Lo que queda aquí es el número que pinta la columna "Oportunidad",
 * y por eso la fórmula tiene que seguir siendo idéntica a la de SQL: la
 * equivalencia está fijada en `tests/test_renovaciones_score.py`. Si cambias
 * una, cambia la otra.
 */

export interface OpportunityInput {
  /** Probabilidad de cambio de adjudicatario (0..1), salida del modelo de retención. */
  riesgoCambio: number | null;
  /** Importe adjudicado del contrato que vence. */
  importe: number | null;
  /** Días hasta el vencimiento efectivo (puede ser negativo si ya venció). */
  diasRestantes: number | null;
  /** Horizonte de la consulta en días (meses × 30); define la escala de urgencia. */
  horizonteDias: number;
}

/**
 * Urgencia normalizada 0..1: 1 cuando vence ya (o ha vencido), decae linealmente
 * hasta 0 al final del horizonte.
 */
export function urgency(diasRestantes: number | null, horizonteDias: number): number {
  if (diasRestantes == null) return 0;
  if (horizonteDias <= 0) return diasRestantes <= 0 ? 1 : 0;
  const u = 1 - diasRestantes / horizonteDias;
  return Math.min(1, Math.max(0, u));
}

/**
 * Score de oportunidad = `riesgo_cambio × importe × urgencia`.
 * Devuelve 0 cuando falta el riesgo o el importe (no se puede priorizar a ciegas).
 */
export function opportunityScore(input: OpportunityInput): number {
  const { riesgoCambio, importe } = input;
  if (riesgoCambio == null || importe == null || importe <= 0) return 0;
  return riesgoCambio * importe * urgency(input.diasRestantes, input.horizonteDias);
}
