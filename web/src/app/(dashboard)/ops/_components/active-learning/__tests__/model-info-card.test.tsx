import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ModelInfoCard } from "../model-info-card";

/**
 * «Sin modelo activo» y «sin modelo registrado» no son lo mismo.
 *
 * En producción el clasificador tenía dos versiones registradas y ninguna
 * activa (la v2 se desactivó al perderse su artefacto), y la ficha decía «Aún
 * no hay un modelo registrado: etiqueta para habilitar el primer
 * entrenamiento». Mandaba a etiquetar para resolver algo que no se arregla
 * etiquetando.
 */

const BASE = {
  stats: undefined,
  metric: null,
  metricTrend: null,
  feedbacksSinceTrain: 12,
};

afterEach(cleanup);

describe("ModelInfoCard", () => {
  it("con versiones registradas y ninguna activa, dice cuál fue la última", () => {
    render(
      <ModelInfoCard
        {...BASE}
        activeModel={null}
        ultimaRegistrada={{ version: 2, trained_at: "2026-09-29T10:00:00+00:00" }}
      />,
    );

    expect(screen.getByText(/Ninguna versión está activa/)).toBeInTheDocument();
    expect(screen.getByText(/v2/)).toBeInTheDocument();
    expect(screen.queryByText(/Aún no hay un modelo registrado/)).not.toBeInTheDocument();
  });

  it("sin ninguna versión, invita al primer entrenamiento", () => {
    render(<ModelInfoCard {...BASE} activeModel={null} ultimaRegistrada={null} />);

    expect(screen.getByText(/Aún no hay un modelo registrado/)).toBeInTheDocument();
    expect(screen.queryByText(/Ninguna versión está activa/)).not.toBeInTheDocument();
  });

  it("con modelo activo enseña su versión y no el aviso", () => {
    render(
      <ModelInfoCard
        {...BASE}
        activeModel={{ version: 3, trained_at: "2026-10-01T10:00:00+00:00", metrics: {} }}
        ultimaRegistrada={{ version: 3, trained_at: "2026-10-01T10:00:00+00:00" }}
      />,
    );

    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.queryByText(/Ninguna versión está activa/)).not.toBeInTheDocument();
  });
});
