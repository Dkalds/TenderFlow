/**
 * Una lista de eventos agrupada por el día en que ocurrieron, para pintarla
 * como línea de tiempo («Hoy», «Ayer», «5 oct 2026»): los movimientos de
 * contrato del Resumen y la actividad del equipo.
 *
 * Solo coloca: los eventos llegan ya ordenados del backend y cada grupo
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

/**
 * `fechaDe` dice de dónde sale la fecha de cada evento; por defecto, su campo
 * `fecha` (el de `GET /eventos`).
 */
export function agruparPorDia<T>(
  eventos: readonly T[],
  ahora: Date,
  fechaDe: (evento: T) => string | null | undefined = (evento) =>
    (evento as { fecha?: string | null }).fecha,
): DiaEventos<T>[] {
  const hoy = claveDia(ahora);
  const ayer = claveDia(new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate() - 1));
  const grupos = new Map<string, DiaEventos<T>>();

  for (const evento of eventos) {
    const cruda = fechaDe(evento);
    const fecha = cruda ? new Date(cruda) : null;
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
