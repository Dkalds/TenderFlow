/**
 * F4.4 — cómo se dice la fecha prevista de adjudicación sin prometerla.
 *
 * El backend manda `expected_award` con su `metodo`, el intervalo p25–p75 y la
 * `n` que lo sostiene, o `null` cuando el órgano no llega al mínimo de
 * adjudicaciones (o falta la fecha límite). Las reglas de presentación viven
 * aquí, fuera del componente, para que la ficha y el tablero digan lo mismo
 * (ADR-014): una **estimación** se presenta como intervalo con su base; sólo
 * un **hito** publicado se presenta como fecha.
 */
import type { Schemas } from "@/lib/api-types";

export type AdjudicacionPrevista = Schemas["ExpectedAward"];

export interface TextoAdjudicacion {
  /** Lo que va en la celda: «sin estimación», una fecha o un intervalo. */
  valor: string;
  /** Una línea de contexto: de dónde sale y sobre cuántos casos. */
  base: string;
  metodo: AdjudicacionPrevista["metodo"] | null;
}

const MES = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric" });

/** `YYYY-MM-DD` → «3 nov 2026». Sin zona: la fecha es de calendario. */
export function fechaCorta(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return MES.format(new Date(Date.UTC(y, m - 1, d, 12)));
}

export function textoAdjudicacion(
  prevista: AdjudicacionPrevista | null | undefined,
): TextoAdjudicacion {
  if (!prevista) {
    return {
      valor: "Sin estimación",
      base: "El órgano no tiene adjudicaciones suficientes para estimarla, o falta la fecha límite.",
      metodo: null,
    };
  }
  if (prevista.metodo === "hito") {
    return {
      valor: fechaCorta(prevista.fecha),
      base: "Fecha publicada por el órgano en el procedimiento.",
      metodo: "hito",
    };
  }
  return {
    valor: `${fechaCorta(prevista.p25)} – ${fechaCorta(prevista.p75)}`,
    base: `Estimación: fecha límite más el plazo habitual del órgano (mediana ${fechaCorta(
      prevista.fecha,
    )}, sobre ${prevista.n} adjudicaciones).`,
    metodo: "estimacion",
  };
}
