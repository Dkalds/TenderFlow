import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  type RadarQuality,
  RadarQualityNota,
  RadarQualityResumen,
} from "@/components/pursuits/radar-quality";

/**
 * S3.2 — el Radar dice si prioriza bien, y sólo cuando puede decirlo.
 *
 * La regla que se fija aquí es la de ADR-014: por debajo del mínimo que declara
 * la propia respuesta no se pinta un porcentaje. El umbral no se comprueba con
 * un número escrito en el test, sino con el `minimo_por_banda` que viene en el
 * dato: si un día el backend lo sube, el componente tiene que seguirlo.
 */

function calidad(overrides: Partial<RadarQuality> = {}): RadarQuality {
  return {
    minimo_por_banda: 10,
    ventana_desde: "2026-06-01T09:00:00Z",
    ventana_hasta: "2026-08-31T09:00:00Z",
    ventana_origen: "historico_observado",
    bandas: [
      {
        banda: "Caliente",
        abiertas: 16,
        cerradas: 12,
        ganadas: 8,
        perdidas: 4,
        resueltas: 12,
        precision: 8 / 12,
        tasa_cierre: 0.75,
        suficiente: true,
      },
      {
        banda: "Tibia",
        abiertas: 5,
        cerradas: 3,
        ganadas: 1,
        perdidas: 2,
        resueltas: 3,
        precision: null,
        tasa_cierre: null,
        suficiente: false,
      },
    ],
    pursuits_con_banda: 21,
    pursuits_total: 40,
    cobertura_pct: 52.5,
    ...overrides,
  };
}

describe("calidad del Radar", () => {
  it("dice la precisión de la banda con su denominador", () => {
    render(<RadarQualityNota calidad={calidad()} banda="Caliente" />);

    expect(screen.getByText(/Precisión de la banda Caliente en tu organización/)).toBeInTheDocument();
    expect(screen.getByText("8/12")).toBeInTheDocument();
  });

  it("por debajo del mínimo dice «sin datos suficientes», no un porcentaje", () => {
    render(<RadarQualityNota calidad={calidad()} banda="Tibia" />);

    expect(screen.getByText("sin datos suficientes")).toBeInTheDocument();
    // Un 33 % sobre tres cierres es una anécdota con formato de dato.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    // Pero la base sí se enseña: es lo que dice cuánto falta.
    expect(screen.getByText(/3 de 10 oportunidades resueltas necesarias/)).toBeInTheDocument();
  });

  it("sin métrica no pinta nada en vez de pintar ceros", () => {
    const { container } = render(<RadarQualityNota calidad={null} banda="Caliente" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("una banda sin oportunidades no inventa una frase", () => {
    const { container } = render(<RadarQualityNota calidad={calidad()} banda="Descarte" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("el resumen declara la ventana y la cobertura", () => {
    render(<RadarQualityResumen calidad={calidad()} />);

    expect(screen.getByText(/Ventana 2026-06-01 → 2026-08-31/)).toBeInTheDocument();
    expect(screen.getByText(/21 de 40 oportunidades guardan la banda/)).toBeInTheDocument();
  });

  it("sin ninguna banda sellada explica por qué no hay métrica", () => {
    render(<RadarQualityResumen calidad={calidad({ bandas: [] })} />);

    expect(screen.getByText(/ninguna oportunidad guarda la banda/)).toBeInTheDocument();
  });
});
