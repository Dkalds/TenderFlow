/**
 * El flujo de una oportunidad tal y como lo impone el backend.
 *
 * Es el espejo de `_TRANSITIONS` y de `_normalize_and_validate_update` en
 * `services/pursuits.py`. Quien decide sigue siendo el backend —todo PATCH se
 * valida allí—; esto existe para que la pantalla no ofrezca un movimiento que
 * va a rechazar. Sin él, el tablero dejaba soltar en cualquier columna y el 409
 * de «Transición no permitida» se leía como «alguien del equipo la movió».
 *
 * El flujo es lineal y sin vuelta atrás: desde cada fase abierta sólo se avanza
 * a la siguiente o se retira, «Ganada» y «Perdida» sólo salen de «Presentada»,
 * y un estado terminal ya no cambia. Si el backend cambia estas reglas, este
 * fichero cambia en el mismo PR.
 */

import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import { esTerminal, type Pursuit, type PursuitStatus } from "@/hooks/use-pursuits";
import type { FaseKey } from "./fases";

/** Los tres estados terminales, que son también los tres resultados de cerrar. */
export type Resultado = "won" | "lost" | "withdrawn";

/** Lo que las reglas miran de una oportunidad. */
export type EstadoFlujo = Pick<Pursuit, "status" | "decision">;

const TRANSICIONES: Record<PursuitStatus, readonly PursuitStatus[]> = {
  identified: ["qualifying", "withdrawn"],
  qualifying: ["go_no_go", "withdrawn"],
  go_no_go: ["preparing", "withdrawn"],
  preparing: ["submitted", "withdrawn"],
  submitted: ["won", "lost", "withdrawn"],
  won: [],
  lost: [],
  withdrawn: [],
};

/** Los estados a los que no se llega sin decisión GO. */
const EXIGEN_GO: readonly PursuitStatus[] = ["preparing", "submitted", "won", "lost"];

const RESULTADOS: readonly Resultado[] = ["won", "lost", "withdrawn"];

export const CERRADA_NO_CAMBIA = "Una oportunidad cerrada ya no cambia de fase.";

/** La fase abierta que sigue a `status`, o `null` si lo único que queda es cerrar. */
export function siguienteFase(status: PursuitStatus): PursuitStatus | null {
  return TRANSICIONES[status].find((destino) => !esTerminal(destino)) ?? null;
}

/**
 * Por qué el backend rechazaría llevar la oportunidad a `destino`, o `null` si
 * lo acepta. Quedarse donde está no es un movimiento y no se bloquea.
 */
export function motivoBloqueo(pursuit: EstadoFlujo, destino: PursuitStatus): string | null {
  const actual = pursuit.status;
  if (destino === actual) return null;
  if (!TRANSICIONES[actual].includes(destino)) {
    if (esTerminal(actual)) return CERRADA_NO_CAMBIA;
    const siguiente = siguienteFase(actual);
    return siguiente
      ? `Desde «${statusLabel(actual)}» solo se avanza a «${statusLabel(siguiente)}» o se retira.`
      : `Desde «${statusLabel(actual)}» solo se registra el resultado o se retira.`;
  }
  if (EXIGEN_GO.includes(destino) && pursuit.decision !== "go") {
    return "Preparar o presentar una oferta exige la decisión GO.";
  }
  if (pursuit.decision === "no_go" && destino !== "withdrawn") {
    return "Con la decisión NO-GO solo cabe retirarla.";
  }
  return null;
}

/** Los resultados con los que se puede cerrar ahora mismo. */
export function resultadosPermitidos(pursuit: EstadoFlujo): Resultado[] {
  if (esTerminal(pursuit.status)) return [];
  return RESULTADOS.filter((resultado) => motivoBloqueo(pursuit, resultado) === null);
}

/**
 * Lo mismo, dicho en columnas del tablero: «Cerradas» acepta la tarjeta si le
 * queda algún resultado posible, y el diálogo de cierre ofrece sólo ésos.
 */
export function bloqueoDeFase(pursuit: EstadoFlujo, fase: FaseKey): string | null {
  if (fase === "cerrada") {
    return resultadosPermitidos(pursuit).length > 0 ? null : CERRADA_NO_CAMBIA;
  }
  return motivoBloqueo(pursuit, fase);
}
