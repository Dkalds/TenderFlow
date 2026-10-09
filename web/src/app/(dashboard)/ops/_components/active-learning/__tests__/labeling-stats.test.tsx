/**
 * Las cifras del etiquetado salen de `GET /feedback/stats` tal como lo publica
 * el contrato: `total`, `positivos`, `negativos` y `last_feedback_at`. La
 * pantalla leía `total_labels`, `pct_relevant` y `last_updated`, que la API no
 * ha servido nunca, así que «Etiquetas totales» y «Última actualización»
 * salían siempre vacías.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { FeedbackStats } from "@/hooks/use-feedback";
import { LabelingStats } from "../labeling-stats";
import { ModelInfoCard } from "../model-info-card";

const STATS: FeedbackStats = {
  total: 57,
  positivos: 40,
  negativos: 17,
  last_feedback_at: "2026-09-27T10:00:00+00:00",
};

describe("Estadísticas del etiquetado", () => {
  it("«Etiquetas totales» es el total de /feedback/stats", () => {
    render(<LabelingStats stats={STATS} statsLoading={false} queueSize={20} queueLoading={false} />);

    expect(screen.getByText("Etiquetas totales").closest("[data-slot='stat-cell']")).toHaveTextContent("57");
  });

  it("la ficha del modelo enseña el total y la fecha de la última etiqueta", () => {
    render(
      <ModelInfoCard
        stats={STATS}
        activeModel={null}
        metric={null}
        metricTrend={null}
        feedbacksSinceTrain={0}
        ultimaRegistrada={null}
      />,
    );

    expect(screen.getByText("Total de etiquetas").nextElementSibling).toHaveTextContent("57");
    expect(screen.getByText("Última actualización").nextElementSibling).not.toHaveTextContent("—");
  });

  it("no enseña un porcentaje de relevantes que la API no calcula", () => {
    render(<LabelingStats stats={STATS} statsLoading={false} queueSize={20} queueLoading={false} />);

    expect(screen.queryByText(/relevantes/i)).toBeNull();
  });
});
