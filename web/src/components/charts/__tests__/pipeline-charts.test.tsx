import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PipelineUrgencyScatter } from "@/components/charts/pipeline-charts";

describe("pipeline charts", () => {
  it("renders the urgency scatter chart", () => {
    expect(() =>
      render(
        <PipelineUrgencyScatter
          data={[
            { id_externo: "1", titulo: "Urgente", dias_restantes: 3, importe: 100000, es_urgente: true },
            { id_externo: "2", titulo: "Normal", dias_restantes: 45, importe: 50000, es_urgente: false },
          ]}
          onPointClick={() => {}}
        />,
      ),
    ).not.toThrow();
  });
});
