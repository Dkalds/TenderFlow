import { describe, expect, it } from "vitest";
import { riesgoLabel } from "../riesgos";

/**
 * Los cuatro sitios que pintan `risk_flags` mostraban el identificador crudo del
 * backend. Estos casos fijan que lo que se ve es castellano, y que un aviso que
 * el backend estrene antes de que exista su entrada aquí no vuelve a salir en
 * snake_case.
 */
describe("riesgoLabel", () => {
  it.each([
    ["sin_historico_competencia", "Sin histórico de competencia"],
    ["sin_senal_tecnica", "Sin señal técnica"],
    ["sin_importe", "Sin importe publicado"],
    ["fuera_de_rango", "Fuera de tu rango de importe"],
  ])("traduce %s", (flag, esperado) => {
    expect(riesgoLabel(flag)).toBe(esperado);
  });

  it("deja legible un aviso que todavía no tiene etiqueta", () => {
    expect(riesgoLabel("sin_datos_de_lote")).toBe("Sin datos de lote");
  });

  it("no rompe con un valor vacío o raro", () => {
    expect(riesgoLabel("")).toBe("");
    expect(riesgoLabel("_")).toBe("_");
  });
});
