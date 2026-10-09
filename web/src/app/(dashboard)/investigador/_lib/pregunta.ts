/**
 * ¿Lo que se escribió es una pregunta al asistente, o una búsqueda?
 *
 * La pantalla tenía dos modos y había que elegir uno antes de escribir. Las dos
 * únicas búsquedas del registro de producción (2026-10-04) eran preguntas
 * —«¿Qué licitaciones han tenido bajada temeraria?»— hechas en el modo
 * «Búsqueda», que era el que venía marcado. Ahora hay una sola caja: siempre
 * se busca, y si además es una pregunta, el asistente la responde.
 *
 * La regla es deliberadamente corta: los signos de interrogación, o una frase
 * que arranca como arranca una pregunta o un encargo. Unas palabras sueltas
 * («licencias SAP») no despiertan al asistente —cuesta y tarda—; para eso
 * queda su botón junto a los resultados.
 */

import { foldText } from "@/lib/utils";

/** Primeras palabras, ya plegadas, con las que arranca una pregunta o un encargo. */
const ARRANQUES = new Set([
  "que",
  "cual",
  "cuales",
  "como",
  "cuando",
  "cuanto",
  "cuanta",
  "cuantos",
  "cuantas",
  "donde",
  "quien",
  "quienes",
  "puedes",
  "podrias",
  "dime",
  "dame",
  "explica",
  "explicame",
  "resume",
  "resumeme",
  "resumen",
  "compara",
  "hay",
  "existe",
  "existen",
]);

export function esPregunta(texto: string): boolean {
  const limpio = texto.trim();
  if (!limpio) return false;
  if (limpio.includes("?") || limpio.includes("¿")) return true;
  const [primera, segunda] = foldText(limpio).split(/\s+/);
  if (primera === "por" && segunda === "que") return true;
  return ARRANQUES.has(primera);
}
