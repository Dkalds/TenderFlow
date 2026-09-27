/**
 * La tarjeta de la cola por desacuerdo (plan de clasificación en tres niveles,
 * F1): por qué está el expediente en la cola, qué propone el LLM y el atajo
 * para aceptarlo de un clic.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { QueueItem } from "../../../_lib/active-learning";
import { QueueItemCard } from "../queue-item-card";

type Props = ComponentProps<typeof QueueItemCard>;

const ITEM: QueueItem = {
  id_externo: "EXP-1",
  titulo: "Mantenimiento de la sede electrónica",
  motivo: "familias_distintas",
  llm: { es_ti: true, confianza_es_ti: 0.9, familias: ["DESARROLLO"], sin_evidencia: false },
};

function pintar(cambios: Partial<Props> = {}): Props {
  const props: Props = {
    item: ITEM,
    activeModel: null,
    chosenTech: null,
    chosenSecs: new Set<string>(),
    note: "",
    noteExpanded: false,
    descExpanded: false,
    isSubmitting: false,
    onSelectTech: vi.fn(),
    onClearSelection: vi.fn(),
    onToggleNote: vi.fn(),
    onToggleDesc: vi.fn(),
    onNoteChange: vi.fn(),
    onConfirm: vi.fn(),
    onNotRelevant: vi.fn(),
    onSkip: vi.fn(),
    onAcceptLlm: vi.fn(),
    onTiWithoutFamily: vi.fn(),
    ...cambios,
  };
  // `TooltipProvider` porque las acciones llevan `Tooltip`, y `Tooltip.Root`
  // de Radix revienta sin proveedor (en la app lo pone `components/providers.tsx`).
  render(
    <TooltipProvider>
      <QueueItemCard {...props} />
    </TooltipProvider>,
  );
  return props;
}

describe("QueueItemCard — cola por desacuerdo", () => {
  it("enseña la propuesta del LLM con su confianza", () => {
    pintar();

    expect(screen.getByText("Propuesta del LLM: es TI · DESARROLLO")).toBeInTheDocument();
    expect(screen.getByText(/90%/)).toBeInTheDocument();
  });

  it("dice por qué está el expediente en la cola", () => {
    pintar();

    expect(screen.getByText("El LLM y las reglas ven familias distintas")).toBeInTheDocument();
  });

  it("un motivo que no conoce se enseña tal cual", () => {
    pintar({ item: { ...ITEM, motivo: "motivo_nuevo" } });

    expect(screen.getByText("motivo_nuevo")).toBeInTheDocument();
  });

  it("«Aceptar propuesta» llama a onAcceptLlm", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "Aceptar propuesta" }));

    expect(props.onAcceptLlm).toHaveBeenCalledTimes(1);
  });

  it("«No es TI» llama a onNotRelevant", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "No es TI" }));

    expect(props.onNotRelevant).toHaveBeenCalledTimes(1);
  });

  it("«Es TI, sin familia» llama a onTiWithoutFamily", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "Es TI, sin familia" }));

    expect(props.onTiWithoutFamily).toHaveBeenCalledTimes(1);
  });

  it("sin propuesta del LLM no pinta «Aceptar propuesta»", () => {
    pintar({ item: { ...ITEM, llm: null } });

    expect(screen.queryByRole("button", { name: "Aceptar propuesta" })).toBeNull();
    expect(screen.queryByText(/Propuesta del LLM/)).toBeNull();
  });

  it("si el LLM dijo que no es TI, la propuesta lo dice", () => {
    pintar({ item: { ...ITEM, llm: { es_ti: false, confianza_es_ti: 0.7, familias: [], sin_evidencia: false } } });

    expect(screen.getByText("Propuesta del LLM: no es TI")).toBeInTheDocument();
  });

  it("sin ml_proba no enseña una confianza inventada", () => {
    // `confidence` es un 0,5 de relleno (el contrato lo exige `float`);
    // `sin_confianza` dice que no es un dato.
    pintar({ item: { ...ITEM, confidence: 0.5, uncertainty: 0, sin_confianza: true } });

    expect(screen.queryByText(/Confianza SAP/)).toBeNull();
    expect(screen.getByText("Sin predicción del modelo disponible.")).toBeInTheDocument();
  });

  it("con ml_proba enseña la confianza del modelo", () => {
    pintar({ item: { ...ITEM, confidence: 0.97, uncertainty: 0.47, sin_confianza: false } });

    expect(screen.getByText(/Confianza SAP/)).toBeInTheDocument();
  });

  it("si el LLM no dijo si es TI, enseña sus familias y no ofrece aceptar", () => {
    // Las respuestas anteriores al prompt v3 traen familias y no el marcador:
    // aceptar no tendría qué enviar como `relevante`.
    pintar({ item: { ...ITEM, llm: { es_ti: null, confianza_es_ti: null, familias: ["SAP"], sin_evidencia: false } } });

    expect(screen.getByText("Familias del LLM: SAP")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aceptar propuesta" })).toBeNull();
  });
});
