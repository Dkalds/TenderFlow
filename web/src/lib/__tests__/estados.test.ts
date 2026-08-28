import { describe, it, expect } from "vitest";
import { estadoLabel } from "@/lib/estados";
import { ESTADO_CHART_COLOR, getEstadoChartColor, CHART_SERIES } from "@/lib/chart-colors";

describe("estadoLabel", () => {
  it("traduce el código PLACSP que devuelve la API", () => {
    expect(estadoLabel("PUB")).toBe("Publicada");
    expect(estadoLabel("EV")).toBe("Evaluación");
    expect(estadoLabel("ADJ")).toBe("Adjudicada");
  });

  it("es idempotente sobre una etiqueta ya resuelta", () => {
    expect(estadoLabel("Publicada")).toBe("Publicada");
  });

  it("devuelve el código crudo si la fuente publica uno nuevo", () => {
    expect(estadoLabel("XYZ")).toBe("XYZ");
  });

  it("traduce las fases PSCP canonizadas por la migración v91", () => {
    // Antes de v91 estas tres llegaban como la etiqueta catalana cruda —y
    // truncada— desde el conector, así que no había código que traducir.
    expect(estadoLabel("AGR")).toBe("Publicación agregada");
    expect(estadoLabel("EJEC")).toBe("En ejecución");
    expect(estadoLabel("CPM")).toBe("Consulta preliminar");
  });

  it("trata el vacío como vacío, no como «Desconocido»", () => {
    expect(estadoLabel(null)).toBe("");
    expect(estadoLabel(undefined)).toBe("");
  });
});

describe("getEstadoChartColor · códigos", () => {
  it("colorea por código, no sólo por etiqueta", () => {
    // El bug que arregla: la API manda `PUB`, la tabla estaba indexada por
    // «Publicada», y el scatter del Resumen pintaba los mil puntos de
    // CHART_SERIES[0] bajo el rótulo «color por estado».
    expect(getEstadoChartColor("PUB")).toBe(ESTADO_CHART_COLOR["Publicada"]);
    expect(getEstadoChartColor("ADJ")).toBe(ESTADO_CHART_COLOR["Adjudicada"]);
  });

  it("da colores distintos a estados distintos", () => {
    const colores = ["PUB", "EV", "ADJ", "RES", "ANUL"].map(getEstadoChartColor);
    expect(new Set(colores).size).toBe(colores.length);
  });

  it("cae a la primera serie con un código desconocido", () => {
    expect(getEstadoChartColor("XYZ")).toBe(CHART_SERIES[0]);
  });

  it("da color propio a la publicación agregada, que es el 93% del corpus", () => {
    // Sin entrada propia caía en CHART_SERIES[0], el mismo color que `PUB`:
    // la barra que domina la composición era indistinguible de la que menos.
    expect(getEstadoChartColor("AGR")).toBe(ESTADO_CHART_COLOR["Publicación agregada"]);
    expect(getEstadoChartColor("AGR")).not.toBe(getEstadoChartColor("PUB"));
  });
});
