import { describe, it, expect } from "vitest";
import {
  etiquetaPeriodo,
  PERIODO_POR_DEFECTO,
  periodoDeUrl,
  rangoDePeriodo,
} from "../_lib/periodo";

/**
 * El periodo de Rendimiento, probado sin montar la vista.
 *
 * Lo importante de este módulo no es el formato de la fecha: es que la ventana
 * sea **estable dentro del mismo día**. Entra en la `queryKey` de las métricas,
 * y una marca de tiempo al milisegundo haría que React Query pidiera otra vez
 * en cada render — un bucle que en pantalla se ve como parpadeo, no como error.
 */

describe("periodoDeUrl", () => {
  it("acepta las tres claves conocidas", () => {
    expect(periodoDeUrl("12m")).toBe("12m");
    expect(periodoDeUrl("anio")).toBe("anio");
    expect(periodoDeUrl("historico")).toBe("historico");
  });

  it("cae al histórico ante ausencia o basura, sin romperse", () => {
    expect(periodoDeUrl(null)).toBe(PERIODO_POR_DEFECTO);
    expect(periodoDeUrl(undefined)).toBe(PERIODO_POR_DEFECTO);
    expect(periodoDeUrl("ayer")).toBe(PERIODO_POR_DEFECTO);
    expect(PERIODO_POR_DEFECTO).toBe("historico");
  });
});

describe("rangoDePeriodo", () => {
  const ahora = new Date("2026-09-21T15:42:07.123Z");

  it("el histórico no acota por ningún extremo", () => {
    expect(rangoDePeriodo("historico", ahora)).toEqual({ desde: null, hasta: null });
  });

  it("«12 meses» retrocede doce meses hasta el inicio del día", () => {
    expect(rangoDePeriodo("12m", ahora)).toEqual({
      desde: "2025-09-21T00:00:00.000Z",
      hasta: null,
    });
  });

  it("«este año» arranca el 1 de enero", () => {
    expect(rangoDePeriodo("anio", ahora)).toEqual({
      desde: "2026-01-01T00:00:00.000Z",
      hasta: null,
    });
  });

  it("dos instantes del mismo día dan la misma ventana", () => {
    const manana = new Date("2026-09-21T06:00:00.000Z");
    const noche = new Date("2026-09-21T23:59:59.999Z");
    expect(rangoDePeriodo("12m", manana)).toEqual(rangoDePeriodo("12m", noche));
  });

  it("«hasta» se deja abierto para no perder lo que ha pasado hoy", () => {
    expect(rangoDePeriodo("12m", ahora).hasta).toBeNull();
    expect(rangoDePeriodo("anio", ahora).hasta).toBeNull();
  });
});

describe("etiquetaPeriodo", () => {
  it("cada clave dice de qué universo habla", () => {
    expect(etiquetaPeriodo("12m")).toBe("Últimos 12 meses");
    expect(etiquetaPeriodo("anio")).toBe("Desde el 1 de enero");
    expect(etiquetaPeriodo("historico")).toContain("Histórico completo");
  });
});
