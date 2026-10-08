import { describe, expect, it } from "vitest";
import { CHART_SERIES } from "@/lib/chart-colors";
import { repartoPorSubtipo } from "../novedades-subtipos";

describe("repartoPorSubtipo", () => {
  it("nombra cada subtipo y le da un color fijo, venga en el orden que venga", () => {
    const reparto = repartoPorSubtipo({ pursuit: 2, documento_nuevo: 3 });
    expect(reparto.map((r) => [r.clave, r.etiqueta, r.n])).toEqual([
      ["documento_nuevo", "Documentos nuevos", 3],
      ["pursuit", "Oportunidades del equipo", 2],
    ]);
    expect(repartoPorSubtipo({ documento_nuevo: 1 })[0].color).toBe(reparto[0].color);
    // Cada tramo empieza donde acaba el anterior.
    expect(reparto.map((r) => r.inicio)).toEqual([0, 3]);
  });

  it("el cajón «cambio» y lo que no se sabe nombrar van en el gris de «Otros»", () => {
    const reparto = repartoPorSubtipo({ cambio: 1, subtipo_nuevo: 2 });
    expect(reparto.map((r) => r.color)).toEqual([CHART_SERIES[7], CHART_SERIES[7]]);
    expect(reparto.map((r) => r.etiqueta)).toEqual(["Otros cambios", "Otro aviso"]);
  });

  it("descarta los subtipos sin ningún cambio", () => {
    expect(repartoPorSubtipo({ recurso: 0 })).toEqual([]);
    expect(repartoPorSubtipo(undefined)).toEqual([]);
  });
});
