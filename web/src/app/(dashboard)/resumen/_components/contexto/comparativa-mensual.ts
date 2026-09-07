/**
 * Delta entre los dos últimos meses **cerrados** de la serie del ámbito.
 *
 * `por_mes` agrupa por `substr(fecha_publicacion, 1, 7)`, así que su último
 * bucket es el mes **en curso**. Comparándolo con el anterior, el día 2 de cada
 * mes la pantalla de entrada abría con «−94 %» y con el badge de anomalía
 * encendido, todos los meses, sin que hubiera pasado nada. Aquí la serie se
 * recorta a meses cerrados y la etiqueta dice cuáles compara («jul vs jun»), no
 * un genérico «vs mes previo».
 *
 * Es puro y está fuera del componente a propósito: es la corrección con más
 * consecuencias de esta pantalla y tiene su propio test.
 */

import { isAnomaly } from "@/lib/anomaly-detection";
import { formatMonth } from "@/lib/utils";

export interface MesAgregado {
  mes: string;
  n_licitaciones: number;
  importe: number;
}

export interface ComparativaMensual {
  count?: number;
  importe?: number;
  medio?: number;
  /** «jul vs jun» — vacío si no hay dos meses cerrados que comparar. */
  etiqueta: string;
  anomaliaCount: boolean;
  anomaliaImporte: boolean;
}

/** Variación porcentual de `curr` sobre `prev`, o `undefined` si no se puede. */
function pctDelta(curr?: number, prev?: number): number | undefined {
  if (curr == null || prev == null || prev === 0) return undefined;
  return ((curr - prev) / prev) * 100;
}

/** Serie mensual sin el mes en curso. */
export function mesesCerrados(porMes: MesAgregado[] | undefined, mesActual: string): MesAgregado[] {
  return (porMes ?? []).filter((mes) => mes.mes < mesActual);
}

/** Compara los dos últimos meses **cerrados** de la serie del ámbito. */
export function compararMeses(
  porMes: MesAgregado[] | undefined,
  mesActual: string,
): ComparativaMensual {
  const cerrados = mesesCerrados(porMes, mesActual);
  if (cerrados.length < 2) {
    return { etiqueta: "", anomaliaCount: false, anomaliaImporte: false };
  }
  const ultimo = cerrados[cerrados.length - 1];
  const previo = cerrados[cerrados.length - 2];
  const mismoAnio = ultimo.mes.slice(0, 4) === previo.mes.slice(0, 4);
  const medioUltimo = ultimo.n_licitaciones ? ultimo.importe / ultimo.n_licitaciones : undefined;
  const medioPrevio = previo.n_licitaciones ? previo.importe / previo.n_licitaciones : undefined;
  const historia = cerrados.slice(0, -1);

  return {
    count: pctDelta(ultimo.n_licitaciones, previo.n_licitaciones),
    importe: pctDelta(ultimo.importe, previo.importe),
    medio: pctDelta(medioUltimo, medioPrevio),
    etiqueta: `${formatMonth(ultimo.mes, !mismoAnio)} vs ${formatMonth(previo.mes, !mismoAnio)}`,
    anomaliaCount: isAnomaly(
      ultimo.n_licitaciones,
      historia.map((mes) => mes.n_licitaciones),
    ),
    anomaliaImporte: isAnomaly(
      ultimo.importe,
      historia.map((mes) => mes.importe),
    ),
  };
}
