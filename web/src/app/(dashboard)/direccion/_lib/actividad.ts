/**
 * Cómo se lee una línea del feed de actividad: el verbo y lo que cambió.
 *
 * El backend manda el tipo del evento y, para `pursuit.updated`, los campos
 * enumerados que cambiaron (`cambios`, de qué valor a qué valor). Aquí sólo se
 * eligen las palabras. Antes toda actualización era «actualizó la
 * oportunidad», que no dice nada: el ledger sabía que se había presentado o
 * perdido, y la pantalla no lo contaba.
 */
import { decisionLabel, outcomeLabel, statusLabel } from "@/components/pursuits/pursuit-presenters";
import type { PursuitDecision, PursuitOutcome, PursuitStatus } from "@/hooks/use-pursuits";
import type { Schemas } from "@/lib/api-types";
import { EMPTY } from "@/lib/utils";
import { etiquetaMotivo } from "@/lib/motivos-perdida";

export type Cambio = Schemas["CambioActividad"];

/**
 * Tipos del ledger `pursuit_events`, como verbo. Un tipo que no esté aquí se
 * enseña tal cual en vez de descartarse: un evento nuevo tiene que verse,
 * aunque sea con su nombre técnico, hasta que alguien le ponga uno.
 */
const VERBO: Record<string, string> = {
  "pursuit.created": "abrió la oportunidad",
  "pursuit.updated": "actualizó la oportunidad",
  checklist_evaluated: "evaluó el go/no-go de",
  kit_item_marcado: "marcó un documento del kit de",
};

const VERBO_RESULTADO: Record<string, string> = {
  won: "marcó como ganada",
  lost: "marcó como perdida",
  cancelled: "retiró",
};

const VERBO_DECISION: Record<string, string> = {
  go: "decidió GO en",
  no_go: "decidió NO-GO en",
};

/** El verbo de la línea: el cambio más significativo manda sobre el tipo. */
export function verboDeEvento(evento: string, cambios: readonly Cambio[] = []): string {
  const resultado = cambios.find((cambio) => cambio.campo === "outcome")?.hasta;
  if (resultado && VERBO_RESULTADO[resultado]) return VERBO_RESULTADO[resultado];
  const decision = cambios.find((cambio) => cambio.campo === "decision")?.hasta;
  if (decision && VERBO_DECISION[decision]) return VERBO_DECISION[decision];
  if (cambios.some((cambio) => cambio.campo === "status")) return "movió";
  return VERBO[evento] ?? evento;
}

function legible(campo: Cambio["campo"], valor: string | null | undefined): string {
  if (valor == null) return EMPTY;
  // Un valor fuera del enumerado conocido se enseña tal cual (los `*Label`
  // devuelven `undefined` para una clave que no conocen).
  switch (campo) {
    case "status":
      return statusLabel(valor as PursuitStatus) ?? valor;
    case "decision":
      return decisionLabel(valor as PursuitDecision) ?? valor;
    case "outcome":
      return outcomeLabel(valor as PursuitOutcome) ?? valor;
    case "outcome_reason_code":
      return etiquetaMotivo(valor);
  }
}

const ROTULO: Record<Cambio["campo"], string> = {
  status: "Etapa",
  decision: "Decisión",
  outcome: "Resultado",
  outcome_reason_code: "Motivo",
};

/** «Etapa: Preparando oferta → Presentada»; el motivo, sólo con el valor nuevo. */
export function etiquetaCambio(cambio: Cambio): string {
  const hasta = legible(cambio.campo, cambio.hasta);
  if (cambio.campo === "outcome_reason_code" || cambio.desde == null) {
    return `${ROTULO[cambio.campo]}: ${hasta}`;
  }
  return `${ROTULO[cambio.campo]}: ${legible(cambio.campo, cambio.desde)} → ${hasta}`;
}
