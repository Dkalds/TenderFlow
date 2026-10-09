/**
 * El plazo de presentación de un resultado, en una frase.
 *
 * Es lo primero que decide si un expediente merece el clic, y la tarjeta no lo
 * enseñaba. Solo dice la fecha y si ya pasó: no cuenta días ni deduce si el
 * expediente sigue vivo —eso lo dice su estado, que va al lado.
 */

import { formatDate } from "@/lib/utils";

export interface Plazo {
  texto: string;
  /** El plazo ya terminó. */
  vencido: boolean;
}

export function plazoDe(fechaLimite: string | null | undefined, ahora: Date = new Date()): Plazo | null {
  if (!fechaLimite) return null;
  const fin = new Date(fechaLimite);
  if (Number.isNaN(fin.getTime())) return null;
  // Una fecha sin hora cierra al final de ese día, no a medianoche.
  if (/^\d{4}-\d{2}-\d{2}$/.test(fechaLimite.trim())) fin.setHours(23, 59, 59, 999);
  const vencido = fin.getTime() < ahora.getTime();
  return {
    texto: vencido ? `Plazo cerrado el ${formatDate(fechaLimite)}` : `Plazo hasta el ${formatDate(fechaLimite)}`,
    vencido,
  };
}
