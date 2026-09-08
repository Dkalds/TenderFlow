import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

/**
 * S3.2 — la franja que cierra el bucle del Radar.
 *
 * `RadarQualityNota` ya tiene su propio suite (la regla del umbral vive allí y
 * no se duplica aquí). Lo que se fija en este fichero es lo que decide la
 * franja: cuándo existe, qué banda encabeza y que el detalle por bandas está
 * plegado hasta que alguien lo pide.
 */

const metricsState: { data?: { radar_quality?: unknown } } = { data: undefined };
vi.mock("@/hooks/use-pursuits", () => ({ usePursuitMetrics: () => metricsState }));

import { RadarCalidad } from "@/app/(dashboard)/radar/_components/radar-calidad";

function banda(overrides: Record<string, unknown> = {}) {
  return {
    banda: "Caliente",
    abiertas: 16,
    cerradas: 12,
    ganadas: 8,
    perdidas: 4,
    resueltas: 12,
    precision: 8 / 12,
    tasa_cierre: 0.75,
    suficiente: true,
    ...overrides,
  };
}

function calidad(bandas: unknown[]) {
  return {
    minimo_por_banda: 10,
    ventana_desde: "2026-06-01T00:00:00Z",
    ventana_hasta: "2026-08-31T00:00:00Z",
    ventana_origen: "historico_observado",
    bandas,
    pursuits_con_banda: 21,
    pursuits_total: 40,
    cobertura_pct: 52.5,
  };
}

beforeEach(() => {
  metricsState.data = undefined;
});

afterEach(() => {
  cleanup();
});

describe("franja de calidad del Radar", () => {
  it("encabeza con la precisión de la banda Caliente y su denominador", () => {
    metricsState.data = { radar_quality: calidad([banda()]) };

    render(<RadarCalidad />);

    expect(
      screen.getByText(/Precisión de la banda Caliente en tu organización/),
    ).toBeInTheDocument();
    expect(screen.getByText("8/12")).toBeInTheDocument();
  });

  it("por debajo del mínimo enseña la base en vez de un porcentaje", () => {
    metricsState.data = {
      radar_quality: calidad([
        banda({ resueltas: 3, ganadas: 1, perdidas: 2, cerradas: 3, precision: null, suficiente: false }),
      ]),
    };

    render(<RadarCalidad />);

    expect(screen.getByText("sin datos suficientes")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("sin ninguna banda sellada no ocupa sitio", () => {
    metricsState.data = { radar_quality: calidad([]) };

    const { container } = render(<RadarCalidad />);

    expect(container).toBeEmptyDOMElement();
  });

  it("sin métrica en la respuesta tampoco", () => {
    metricsState.data = {};

    const { container } = render(<RadarCalidad />);

    expect(container).toBeEmptyDOMElement();
  });

  it("con bandas pero ninguna Caliente no inventa la frase de la Caliente", () => {
    metricsState.data = { radar_quality: calidad([banda({ banda: "Tibia" })]) };

    render(<RadarCalidad />);

    expect(screen.queryByText(/Precisión de la banda Caliente/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Ninguna oportunidad abierta desde la banda Caliente/),
    ).toBeInTheDocument();
  });

  it("el detalle por bandas está plegado hasta que se pide", () => {
    metricsState.data = { radar_quality: calidad([banda()]) };

    render(<RadarCalidad />);
    const boton = screen.getByRole("button", { name: /Ver todas las bandas/ });
    expect(boton).toHaveAttribute("aria-expanded", "false");
    // La ventana y la cobertura viven en el resumen: plegado, no se leen.
    expect(screen.getByText(/Ventana 2026-06-01 → 2026-08-31/)).not.toBeVisible();

    fireEvent.click(boton);

    expect(screen.getByRole("button", { name: /Ocultar bandas/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText(/Ventana 2026-06-01 → 2026-08-31/)).toBeVisible();
    expect(screen.getByText(/21 de 40 oportunidades guardan la banda/)).toBeVisible();
  });
});
