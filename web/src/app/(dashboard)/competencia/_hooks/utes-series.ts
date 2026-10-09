/**
 * Las series de la vista de UTE, como funciones puras.
 *
 * No hay fetch ni React: reciben lo que `use-utes-data.ts` ya descargó. Quién
 * forma UTE con quién, cuántas y por cuánto lo agrega la API; aquí sólo se le
 * da forma para pintarlo —ordenar, filtrar por el buscador y medir cada barra
 * contra el máximo visible—, sin totales, medias ni recuentos nuevos.
 */

import type { Schemas } from "@/lib/api-types";
import { foldText, formatMonth } from "@/lib/utils";

type Kpis = Schemas["UTEKpis"];
type Ute = Schemas["UTEMiembro"];
type SocioPar = Schemas["UTESocioPar"];
type MesEvolucion = Schemas["UTEEvolucion"];

/** La parte de `valor` sobre `maximo`, de 0 a 100; sin máximo no hay barra. */
const aEscala = (valor: number, maximo: number) => (maximo > 0 ? (valor * 100) / maximo : 0);

/* ── Importe medio por contrato ───────────────────────────────────────── */

/**
 * Un importe medio sólo es un dato si hay contratos sobre los que hacerlo: sin
 * ellos la API manda un cero, y «el contrato medio es de 0 €» afirmaría algo
 * que nadie ha medido. Ese cero se lee aquí como ausencia.
 */
export function importeMedioConDato(valor: number | null | undefined): number | null {
  return valor != null && valor > 0 ? valor : null;
}

export interface BarraImporteMedio {
  clave: "ute" | "solitario";
  etiqueta: string;
  valor: number | null;
  /** Ancho de la barra, a escala de la mayor de las dos. */
  pct: number;
}

/** Las dos barras pareadas de la tira: el contrato medio en UTE y en solitario. */
export function barrasImporteMedio(kpis: Kpis | undefined): BarraImporteMedio[] {
  const ute = importeMedioConDato(kpis?.ticket_medio_ute);
  const solitario = importeMedioConDato(kpis?.ticket_medio_individual);
  const mayor = Math.max(0, ...[ute, solitario].filter((valor): valor is number => valor != null));
  const barra = (clave: BarraImporteMedio["clave"], etiqueta: string, valor: number | null): BarraImporteMedio => ({
    clave,
    etiqueta,
    valor,
    pct: valor == null ? 0 : aEscala(valor, mayor),
  });
  return [barra("ute", "En UTE", ute), barra("solitario", "En solitario", solitario)];
}

/* ── Alianzas ─────────────────────────────────────────────────────────── */

export interface FilaAlianza {
  clave: string;
  /** «A + B» en la lista de pares; el socio en la de una empresa elegida. */
  nombre: string;
  /** La empresa que elige la fila al pulsarla. */
  empresa: string;
  contratos: number;
  importe: number;
  /** Ancho de la barrita, a escala de la fila con más UTE de las visibles. */
  pct: number;
}

/**
 * La lista que acompaña a la red. Sin empresa elegida, todos los pares; con
 * una, sólo sus socios. En los dos casos del par más repetido al menos, y a
 * igualdad por importe.
 */
export function filasAlianzas(pares: readonly SocioPar[] | undefined, elegida: string | null): FilaAlianza[] {
  const propios = (pares ?? []).filter(
    (par) => elegida == null || par.empresa_a === elegida || par.empresa_b === elegida,
  );
  const filas = propios.map((par, i) => {
    const socio = par.empresa_a === elegida ? par.empresa_b : par.empresa_a;
    return {
      clave: `${i}:${par.empresa_a}:${par.empresa_b}`,
      nombre: elegida == null ? `${par.empresa_a} + ${par.empresa_b}` : socio,
      empresa: socio,
      contratos: par.contratos,
      importe: par.importe,
    };
  });
  filas.sort(
    (a, b) => b.contratos - a.contratos || b.importe - a.importe || a.nombre.localeCompare(b.nombre, "es"),
  );
  const masRepetido = Math.max(0, ...filas.map((fila) => fila.contratos));
  return filas.map((fila) => ({ ...fila, pct: aEscala(fila.contratos, masRepetido) }));
}

/* ── Mariposa ─────────────────────────────────────────────────────────── */

/** Cuántas UTE del ranking se pintan en la mariposa. */
export const FILAS_MARIPOSA = 12;

/** Una fila de la mariposa: las dos medidas, cada una a escala de su máximo visible. */
export interface FilaMariposa {
  nombre: string;
  /** El puesto en el ranking recibido, que no cambia al buscar. */
  puesto: number;
  count: number;
  importe: number;
  pctCount: number;
  pctImporte: number;
}

/**
 * Las UTE con más adjudicaciones, filtradas por el buscador. El buscador sólo
 * mira la lista recibida —las primeras del ámbito—, sin mayúsculas ni tildes.
 */
export function filasMariposa(utes: readonly Ute[] | undefined, busqueda: string): FilaMariposa[] {
  const ranking = [...(utes ?? [])]
    .sort((a, b) => b.count - a.count || b.importe - a.importe || a.nombre.localeCompare(b.nombre, "es"))
    .map((ute, i) => ({ ...ute, puesto: i + 1 }));
  const buscado = foldText(busqueda.trim());
  const visibles = (buscado ? ranking.filter((ute) => foldText(ute.nombre).includes(buscado)) : ranking).slice(
    0,
    FILAS_MARIPOSA,
  );
  const maxCount = Math.max(0, ...visibles.map((ute) => ute.count));
  const maxImporte = Math.max(0, ...visibles.map((ute) => ute.importe));
  return visibles.map((ute) => ({
    nombre: ute.nombre,
    puesto: ute.puesto,
    count: ute.count,
    importe: ute.importe,
    pctCount: aEscala(ute.count, maxCount),
    pctImporte: aEscala(ute.importe, maxImporte),
  }));
}

/* ── Evolución ────────────────────────────────────────────────────────── */

/** Con menos meses que éstos, las columnas no ocupan todo el ancho. */
const COLUMNAS_MINIMAS = 12;

/** Cuántos rótulos caben, como mucho, en el eje de los meses. */
const ROTULOS_EN_EJE = 4;

export interface ColumnaEvolucion {
  period: string;
  /** El mes en forma legible: «2026-01» → «ene 2026». */
  etiqueta: string;
  contratos: number;
  importe: number;
  pctContratos: number;
  pctImporte: number;
  /**
   * Si su rótulo va en el eje: uno de cada tantos, y sólo si tiene a su derecha
   * el sitio de un paso entero, para que ni se pisen ni se salgan del panel.
   */
  enEje: boolean;
}

export interface SerieEvolucion {
  columnas: ColumnaEvolucion[];
  /** El mes con más UTE y el de más importe: lo que mide la columna más alta. */
  maxContratos: number | null;
  maxImporte: number | null;
  /** Huecos vacíos a la derecha cuando hay pocos meses. */
  relleno: number;
}

/**
 * Los meses de la evolución, en orden, con las dos medidas a escala de su
 * propio máximo: dos gráficos que comparten el eje de los meses, no un eje con
 * dos escalas. Un mes que la API no manda no se rellena con un cero.
 */
export function serieEvolucion(evolucion: readonly MesEvolucion[] | undefined): SerieEvolucion {
  const meses = [...(evolucion ?? [])].sort((a, b) => a.period.localeCompare(b.period));
  if (meses.length === 0) return { columnas: [], maxContratos: null, maxImporte: null, relleno: 0 };

  const maxContratos = Math.max(...meses.map((mes) => mes.contratos));
  const maxImporte = Math.max(...meses.map((mes) => mes.importe));
  const huecos = Math.max(meses.length, COLUMNAS_MINIMAS);
  const paso = Math.ceil(huecos / ROTULOS_EN_EJE);

  return {
    columnas: meses.map((mes, i) => ({
      period: mes.period,
      etiqueta: formatMonth(mes.period, true),
      contratos: mes.contratos,
      importe: mes.importe,
      pctContratos: aEscala(mes.contratos, maxContratos),
      pctImporte: aEscala(mes.importe, maxImporte),
      enEje: i % paso === 0 && i + paso <= huecos,
    })),
    maxContratos,
    maxImporte,
    relleno: huecos - meses.length,
  };
}
