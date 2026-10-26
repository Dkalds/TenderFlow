/**
 * D55: sin versión activa del clasificador SAP que haya pasado el gate, la cola
 * no enseña su confianza (la API manda `sin_confianza`) y explica por qué.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ActiveLearning } from "../../../_hooks/use-active-learning";
import type { SenalClasificador, Strategy } from "../../../_lib/active-learning";
import { LabelingQueue } from "../labeling-queue";

const AVISO = /La confianza del clasificador SAP no se muestra/;

function estado(strategy: Strategy, senalClasificador: SenalClasificador | null): ActiveLearning {
  // Solo lo que la cola vacía lee; el resto del hook no participa.
  return {
    items: [],
    pendingItems: [],
    queueLoading: false,
    queueError: null,
    retryQueue: vi.fn(),
    dismissedCount: 0,
    strategy,
    setStrategy: vi.fn(),
    senalClasificador,
  } as unknown as ActiveLearning;
}

const NO_VALIDADA: SenalClasificador = { validada: false, motivo: "sin_version_activa", version: null };

describe("LabelingQueue — señal del clasificador (D55)", () => {
  it("avisa de que la confianza no se muestra si el clasificador no está validado", () => {
    render(<LabelingQueue estado={estado("desacuerdo", NO_VALIDADA)} />);
    expect(screen.getByText(AVISO)).toBeInTheDocument();
  });

  it("no avisa en la cola aleatoria, que no usa el clasificador SAP", () => {
    render(<LabelingQueue estado={estado("random", NO_VALIDADA)} />);
    expect(screen.queryByText(AVISO)).not.toBeInTheDocument();
  });

  it("no avisa con una versión validada", () => {
    render(<LabelingQueue estado={estado("uncertainty", { validada: true, motivo: null, version: 3 })} />);
    expect(screen.queryByText(AVISO)).not.toBeInTheDocument();
  });
});
