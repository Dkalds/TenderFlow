import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PesosScoringCard } from "../_components/pesos-scoring-card";

/**
 * F1.4 — la penalización por órgano que anula a menudo no es una dimensión:
 * no tiene slider ni cuenta en el 100, se enciende o se apaga (peso 0).
 */

const PESOS = {
  importe: 20,
  plazo: 15,
  competencia: 20,
  margen: 20,
  afinidad: 15,
  senal_tecnica: 10,
  organo_anula_frecuente: 8,
};

describe("PesosScoringCard · penalización F1.4", () => {
  it("no pinta slider para la penalización y la ofrece como interruptor", () => {
    render(
      <PesosScoringCard weights={PESOS} total={100} weightsValid onWeightChange={vi.fn()} onReset={vi.fn()} />,
    );
    expect(screen.getAllByRole("slider")).toHaveLength(6);
    expect(screen.getByRole("switch", { name: /Penalizar órganos que anulan/ })).toBeChecked();
  });

  it("apagarla la pone a 0 y encenderla le devuelve su peso", () => {
    const onWeightChange = vi.fn();
    const { rerender } = render(
      <PesosScoringCard weights={PESOS} total={100} weightsValid onWeightChange={onWeightChange} onReset={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("switch", { name: /Penalizar órganos que anulan/ }));
    expect(onWeightChange).toHaveBeenCalledWith("organo_anula_frecuente", 0);

    rerender(
      <PesosScoringCard
        weights={{ ...PESOS, organo_anula_frecuente: 0 }}
        total={100}
        weightsValid
        onWeightChange={onWeightChange}
        onReset={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("switch", { name: /Penalizar órganos que anulan/ }));
    expect(onWeightChange).toHaveBeenLastCalledWith("organo_anula_frecuente", 8);
  });
});
