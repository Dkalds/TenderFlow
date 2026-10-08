/**
 * Los movimientos de contrato agrupados por el día en que ocurrieron, para
 * pintarlos como línea de tiempo («Hoy», «Ayer», «5 oct 2026»).
 *
 * Solo coloca: los eventos llegan ya ordenados de `GET /eventos` y cada grupo
 * conserva ese orden. El día es el del navegador, como el resto de fechas de la
 * consola.
 */

import { formatDate } from "@/lib/utils";

export interface DiaEventos<T> {
  clave: string;
  etiqueta: string;
  eventos: T[];
}

function claveDia(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function agruparPorDia<T extends { fecha?: string | null }>(
  eventos: readonly T[],
  ahora: Date,
): DiaEventos<T>[] {
  const hoy = claveDia(ahora);
  const ayer = claveDia(new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate() - 1));
  const grupos = new Map<string, DiaEventos<T>>();

  for (const evento of eventos) {
    const fecha = evento.fecha ? new Date(evento.fecha) : null;
    const valida = fecha !== null && !Number.isNaN(fecha.getTime());
    const clave = valida ? claveDia(fecha) : "sin-fecha";
    let grupo = grupos.get(clave);
    if (!grupo) {
      const etiqueta = !valida ? "Sin fecha" : clave === hoy ? "Hoy" : clave === ayer ? "Ayer" : formatDate(fecha);
      grupo = { clave, etiqueta, eventos: [] };
      grupos.set(clave, grupo);
    }
    grupo.eventos.push(evento);
  }

  // Lo que no trae fecha no se puede colocar en la línea: al final.
  const sinFecha = grupos.get("sin-fecha");
  grupos.delete("sin-fecha");
  return sinFecha ? [...grupos.values(), sinFecha] : [...grupos.values()];
}
