/**
 * Tests de las series de `_hooks/competidores-series.ts` que hablan del reparto
 * del mercado: el orden por la medida activa, la concentración del titular, la
 * barra al 100 %, los meses del año, las escalas del ranking, el cara a cara y
 * qué empresa queda abierta.
 *
 * Lo que se comprueba aquí es lo que un cambio descuidado rompe sin que la UI
 * se queje: qué entra en «Otras», cuándo una cifra es parcial y qué pasa con
 * una empresa que no trae el dato.
 */
import { describe, it, expect } from "vitest";

import {
  MONTH_LABELS,
  buildConcentracion,
  buildDuelo,
  buildEstacionalidad,
  buildReparto,
  cuotaDe,
  escalasRanking,
  mesPico,
  ordenarPorMetrica,
  resolverAbierta,
  resolverRival,
} from "../_hooks/competidores-series";

import { ACME, BETA, GAMMA, competitor } from "./competidores-fixtures";

const MERCADO = [ACME, BETA, GAMMA];

/* ── Orden y cuota ──────────────────────────────────────────────────── */

describe("ordenarPorMetrica", () => {
  it("por importe y por adjudicaciones dan órdenes distintos", () => {
    expect(ordenarPorMetrica(MERCADO, "importe").map((c) => c.nombre)).toEqual([
      "Acme Sistemas",
      "Beta Consulting",
      "Gamma Redes",
    ]);
    // Gamma gana más veces que Beta, aunque menos dinero.
    expect(ordenarPorMetrica(MERCADO, "count").map((c) => c.nombre)).toEqual([
      "Acme Sistemas",
      "Gamma Redes",
      "Beta Consulting",
    ]);
  });

  it("no muta la lista de entrada", () => {
    const items = [GAMMA, ACME];
    ordenarPorMetrica(items, "importe");
    expect(items[0]).toBe(GAMMA);
  });
});

describe("cuotaDe", () => {
  it("por importe es la cuota que manda la API, sin recalcular", () => {
    expect(cuotaDe(ACME, "importe", 999)).toBe(40);
  });

  it("por adjudicaciones es su recuento sobre el total del ámbito", () => {
    expect(cuotaDe(ACME, "count", 50)).toBe(20);
  });

  it("sin total del ámbito no hay cuota por adjudicaciones", () => {
    // Dividir por la suma de lo recibido daría la cuota entre los 100 primeros,
    // que no es la del mercado.
    expect(cuotaDe(ACME, "count", null)).toBeNull();
    expect(cuotaDe(ACME, "count", 0)).toBeNull();
  });
});

/* ── Concentración del titular ──────────────────────────────────────── */

describe("buildConcentracion", () => {
  const totales = { totalAdjudicaciones: 50, totalEmpresas: 3 };

  it("suma las cuotas de la API de las primeras por importe", () => {
    expect(buildConcentracion(MERCADO, "importe", totales)).toEqual({ pct: 64, n: 3, parcial: false });
  });

  it("por adjudicaciones, los recuentos sobre el total del ámbito", () => {
    // 10 + 7 + 4 = 21 de 50.
    expect(buildConcentracion(MERCADO, "count", totales)).toEqual({ pct: 42, n: 3, parcial: false });
  });

  it("solo cuenta las n primeras", () => {
    expect(buildConcentracion(MERCADO, "importe", totales, 2)).toEqual({ pct: 56, n: 2, parcial: false });
  });

  it("por importe es parcial si la API no devolvió todas las empresas", () => {
    // La lista llega ordenada por adjudicaciones: la primera por importe puede
    // haberse quedado fuera del corte, y la vista tiene que decirlo.
    const parcial = buildConcentracion(MERCADO, "importe", { totalAdjudicaciones: 50, totalEmpresas: 214 });
    expect(parcial.parcial).toBe(true);
  });

  it("por adjudicaciones nunca es parcial: la lista ya viene en ese orden", () => {
    const exacta = buildConcentracion(MERCADO, "count", { totalAdjudicaciones: 50, totalEmpresas: 214 });
    expect(exacta.parcial).toBe(false);
  });

  it("sin competidores no hay cifra", () => {
    expect(buildConcentracion([], "importe", totales)).toEqual({ pct: null, n: 0, parcial: false });
  });

  it("sin total del ámbito no hay cifra por adjudicaciones", () => {
    expect(buildConcentracion(MERCADO, "count", { totalAdjudicaciones: null, totalEmpresas: 3 }).pct).toBeNull();
  });
});

/* ── Reparto en barra al 100 % ──────────────────────────────────────── */

describe("buildReparto", () => {
  const totales = { totalAdjudicaciones: 50, totalEmpresas: 10 };

  it("las primeras con nombre y el resto del mercado en un solo tramo", () => {
    const tramos = buildReparto(MERCADO, "importe", totales, null, 2);
    expect(tramos.map((t) => [t.nombre, t.pct, t.esOtros])).toEqual([
      ["Acme Sistemas", 40, false],
      ["Beta Consulting", 16, false],
      ["Otras 8 empresas", 44, true],
    ]);
  });

  it("«Otras» es el resto hasta 100, no la suma de lo recibido", () => {
    // Gamma (8 %) cae en «Otras» junto a las 7 que la API no devolvió.
    const otros = buildReparto(MERCADO, "importe", totales, null, 2).at(-1);
    expect(otros?.pct).toBe(44);
  });

  it("sin resto no hay tramo «Otras»", () => {
    const dos = [competitor({ nombre: "A", cuota: 60, importe: 6 }), competitor({ nombre: "B", cuota: 40, importe: 4 })];
    const tramos = buildReparto(dos, "importe", { totalAdjudicaciones: 2, totalEmpresas: 2 }, null);
    expect(tramos.map((t) => t.nombre)).toEqual(["A", "B"]);
  });

  it("marca el tramo de la empresa abierta", () => {
    const tramos = buildReparto(MERCADO, "importe", totales, "Beta Consulting", 2);
    expect(tramos.map((t) => t.seleccionado)).toEqual([false, true, false]);
  });

  it("por adjudicaciones sin total del ámbito no dibuja nada", () => {
    expect(buildReparto(MERCADO, "count", { totalAdjudicaciones: null, totalEmpresas: 10 }, null)).toEqual([]);
  });

  it("vacío sin competidores", () => {
    expect(buildReparto([], "importe", totales, null)).toEqual([]);
  });
});

/* ── Meses del año ──────────────────────────────────────────────────── */

describe("buildEstacionalidad", () => {
  it("vacío sin datos", () => {
    expect(buildEstacionalidad(undefined)).toEqual([]);
    expect(buildEstacionalidad([])).toEqual([]);
  });

  it("rellena los doce meses aunque solo llegue uno", () => {
    // Saltarse un mes sin datos desplazaría el eje: diciembre aparecería
    // pegado a marzo.
    const serie = buildEstacionalidad([{ mes: 3, count: 4, importe: 900 }]);
    expect(serie).toHaveLength(12);
    expect(serie.map((p) => p.mes)).toEqual(MONTH_LABELS);
    expect(serie[2]).toEqual({ mes: "Mar", count: 4, importe: 900 });
    expect(serie[0]).toEqual({ mes: "Ene", count: 0, importe: 0 });
  });
});

describe("mesPico", () => {
  it("el mes con más adjudicaciones", () => {
    const serie = buildEstacionalidad([
      { mes: 3, count: 4, importe: 1 },
      { mes: 12, count: 9, importe: 1 },
    ]);
    expect(mesPico(serie)).toEqual({ indice: 11, count: 9 });
  });

  it("sin actividad no hay pico", () => {
    expect(mesPico([])).toBeNull();
    expect(mesPico(buildEstacionalidad([{ mes: 1, count: 0, importe: 0 }]))).toBeNull();
  });
});

/* ── Escalas del ranking ────────────────────────────────────────────── */

describe("escalasRanking", () => {
  it("el máximo de cada medida entre las filas visibles", () => {
    expect(escalasRanking(MERCADO)).toEqual({ cuota: 40, baja: 20, ofertas: 3.5 });
  });

  it("una medida que ninguna fila trae no tiene escala", () => {
    // Un máximo de 0 pintaría todas las barras vacías, como si se hubiera
    // medido y nadie bajara el precio.
    expect(escalasRanking([GAMMA])).toEqual({ cuota: 8, baja: null, ofertas: null });
  });

  it("sin filas no hay escalas", () => {
    expect(escalasRanking([])).toEqual({ cuota: null, baja: null, ofertas: null });
  });
});

/* ── Cara a cara ────────────────────────────────────────────────────── */

describe("buildDuelo", () => {
  const filas = buildDuelo(ACME, BETA);
  const fila = (clave: string) => filas.find((f) => f.clave === clave)!;

  it("ocho medidas, en el mismo orden para las dos", () => {
    expect(filas.map((f) => f.clave)).toEqual([
      "cuota",
      "count",
      "importe_medio",
      "baja_media",
      "ofertas_medias",
      "pct_monopolio",
      "n_organos",
      "pct_top_organo",
    ]);
  });

  it("cada barra va a escala del mayor de los dos", () => {
    // Acme 10 adjudicaciones, Beta 4: 100 y 40.
    expect(fila("count")).toMatchObject({ a: 10, b: 4, pctA: 100, pctB: 40, mayorA: true, mayorB: false });
  });

  it("en un empate ninguna destaca", () => {
    expect(fila("importe_medio")).toMatchObject({ pctA: 100, pctB: 100, mayorA: false, mayorB: false });
  });

  it("un 0 medido es un dato: barra vacía, pero con cifra", () => {
    expect(fila("pct_monopolio")).toMatchObject({ a: 10, b: 0, pctB: 0 });
  });

  it("una medida ausente sale `null`, no 0", () => {
    // «0 % de baja» afirmaría que Gamma gana a precio de salida; lo que se sabe
    // es que no hay baja publicada.
    const conGamma = buildDuelo(ACME, GAMMA);
    const baja = conGamma.find((f) => f.clave === "baja_media")!;
    expect(baja).toMatchObject({ a: 20, b: null, pctA: 100, pctB: 0, mayorA: false, mayorB: false });
  });

  it("los valores por defecto del backend (importe medio y órganos a 0) son ausencia", () => {
    const conGamma = buildDuelo(ACME, GAMMA);
    expect(conGamma.find((f) => f.clave === "importe_medio")?.b).toBeNull();
    expect(conGamma.find((f) => f.clave === "n_organos")?.b).toBeNull();
    expect(conGamma.find((f) => f.clave === "pct_top_organo")?.b).toBeNull();
  });
});

/* ── Qué empresa queda abierta ──────────────────────────────────────── */

describe("resolverAbierta", () => {
  const ordenados = [ACME, BETA, GAMMA];

  it("sin elegir ninguna, la primera del ranking", () => {
    expect(resolverAbierta(ordenados, null, false)).toBe(ACME);
  });

  it("la elegida, si sigue en la lista", () => {
    expect(resolverAbierta(ordenados, "Beta Consulting", false)).toBe(BETA);
  });

  it("si la elegida ya no está (cambió el ámbito), vuelve a la primera", () => {
    expect(resolverAbierta(ordenados, "Fantasma SL", false)).toBe(ACME);
  });

  it("cerrado es cerrado: no reabre la primera", () => {
    expect(resolverAbierta(ordenados, null, true)).toBeNull();
  });

  it("sin competidores no hay nada que abrir", () => {
    expect(resolverAbierta([], null, false)).toBeNull();
  });
});

describe("resolverRival", () => {
  it("la empresa pedida, si está en los datos", () => {
    expect(resolverRival(MERCADO, "Beta Consulting", ACME)).toBe(BETA);
  });

  it("nadie se compara consigo misma", () => {
    expect(resolverRival(MERCADO, "Acme Sistemas", ACME)).toBeNull();
  });

  it("sin rival, sin perfil abierto o con un rival que ya no está, no hay cara a cara", () => {
    expect(resolverRival(MERCADO, null, ACME)).toBeNull();
    expect(resolverRival(MERCADO, "Beta Consulting", null)).toBeNull();
    expect(resolverRival(MERCADO, "Fantasma SL", ACME)).toBeNull();
  });
});
