/**
 * Lecturas puras de «Mercado por segmento»: zonas del HHI, qué se puede
 * preguntar de un segmento, qué parte de la barra entiende `/bajas` y la base
 * de importe.
 */
import { describe, expect, it } from "vitest";

import {
  consultasDeSegmento,
  escalaBajas,
  etiquetaHhi,
  filtrosNoAplicados,
  nombreSegmento,
  ordenarSegmentos,
  parametrosBajas,
  posicionEnEscala,
  textoBase,
  zonaHhi,
  type BajaAgregada,
  type HhiSegmento,
} from "../_hooks/mercado-segmentos";

const segmento = (s: string, hhi: number, importe: number): HhiSegmento => ({
  segmento: s,
  hhi,
  empresas: 3,
  contratos: 9,
  importe_total: importe,
});

const baja = (grupo: string, min: number | null, media: number | null, max: number | null): BajaAgregada => ({
  grupo,
  contratos: 4,
  baja_media_pct: media,
  baja_min_pct: min,
  baja_max_pct: max,
  importe_total: 1,
  ofertas_medias: null,
});

describe("zonas del HHI", () => {
  it("usa los umbrales 1.500 y 2.500, con el umbral dentro de la zona de arriba", () => {
    expect(zonaHhi(1499)).toBe("competitivo");
    expect(zonaHhi(1500)).toBe("moderado");
    expect(zonaHhi(2499)).toBe("moderado");
    expect(zonaHhi(2500)).toBe("concentrado");
    expect(etiquetaHhi(531)).toBe("Mercado competitivo");
    expect(etiquetaHhi(8347)).toBe("Mercado concentrado");
  });
});

describe("segmentos", () => {
  it("por importe reordena sin tocar el orden de la API", () => {
    const api = [segmento("72", 8000, 10), segmento("48", 3333, 300), segmento("30", 900, 50)];
    expect(ordenarSegmentos(api, "concentracion").map((s) => s.segmento)).toEqual(["72", "48", "30"]);
    expect(ordenarSegmentos(api, "importe").map((s) => s.segmento)).toEqual(["48", "30", "72"]);
    expect(api.map((s) => s.segmento)).toEqual(["72", "48", "30"]);
  });

  it("nombra la división CPV con la tabla del perfil de empresa", () => {
    expect(nombreSegmento("cpv", "72")).toBe("72 · Servicios TI y consultoría tecnológica");
    expect(nombreSegmento("ccaa", "Galicia")).toBe("Galicia");
    expect(nombreSegmento("organo", null)).toBe("Sin identificar");
  });

  it("solo pide lo que cada endpoint sabe filtrar", () => {
    expect(consultasDeSegmento("cpv", "72")).toEqual({ cuota: { cpv: "72" }, referencia: { cpv: "72" } });
    expect(consultasDeSegmento("ccaa", "Madrid")).toEqual({ cuota: { ccaa: "Madrid" }, referencia: null });
    expect(consultasDeSegmento("organo", "Ministerio X")).toEqual({
      cuota: null,
      referencia: { organo: "Ministerio X" },
    });
    expect(consultasDeSegmento("tecnologia", "SAP")).toEqual({ cuota: null, referencia: null });
    expect(consultasDeSegmento("cpv", null)).toEqual({ cuota: null, referencia: null });
  });

  it("no pide un valor más largo que el max_length de la ruta: sería un 422", () => {
    expect(consultasDeSegmento("organo", "x".repeat(301)).referencia).toBeNull();
    expect(consultasDeSegmento("ccaa", "x".repeat(51)).cuota).toBeNull();
  });
});

describe("bajas", () => {
  it("de la barra global solo pasan comunidad, fechas e importe mínimo", () => {
    const barra = {
      q: "sap",
      ccaa: "Madrid,Galicia",
      fecha_desde: "2026-01-01",
      fecha_hasta: "2026-06-30",
      importe_min: "10000",
      importe_max: "90000",
      tecnologia: "SAP",
    };
    expect(parametrosBajas(barra)).toEqual({
      ccaa: "Madrid,Galicia",
      fecha_desde: "2026-01-01",
      fecha_hasta: "2026-06-30",
      importe_min: "10000",
    });
    expect(filtrosNoAplicados(barra)).toEqual(["texto", "tecnología", "importe máximo"]);
    expect(filtrosNoAplicados({ ccaa: "Madrid" })).toEqual([]);
  });

  it("la escala parte de 0 o de la baja negativa más baja", () => {
    expect(escalaBajas([baja("A", 5, 10, 30), baja("B", 2, 8, 12)])).toEqual({ min: 0, max: 30 });
    expect(escalaBajas([baja("A", -10, 5, 20)])).toEqual({ min: -10, max: 20 });
    // Sin rangos no hay división por cero.
    expect(escalaBajas([baja("A", null, null, null)])).toEqual({ min: 0, max: 1 });
    expect(posicionEnEscala(5, { min: -10, max: 20 })).toBe(50);
    expect(posicionEnEscala(99, { min: 0, max: 20 })).toBe(100);
  });

  it("dice sobre qué base de importe se calculó", () => {
    expect(textoBase("mixta")).toMatch(/^Base mixta/);
    expect(textoBase("sin_iva")).toMatch(/sin IVA declarada/);
    expect(textoBase(undefined)).toMatch(/Sin base de importe declarada/);
  });
});
