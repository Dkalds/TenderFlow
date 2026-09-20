import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Pursuit } from "@/hooks/use-pursuits";
import { DialogoCierre } from "../_components/dialogo-cierre";

const pursuit = {
  id: 9,
  organization_id: 7,
  licitacion_id: "2026/0410",
  tender_title: "Plataforma de gestión documental",
  status: "submitted",
  decision: "go",
  outcome: "pending",
  version: 4,
} as Pursuit;

describe("DialogoCierre", () => {
  it("ofrece solo los resultados que el flujo permite", () => {
    render(
      <DialogoCierre
        pursuit={pursuit}
        resultados={["withdrawn"]}
        onCancelar={vi.fn()}
        onConfirmar={vi.fn()}
      />,
    );
    expect(screen.getByText("Retirar la oportunidad")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ganada" })).not.toBeInTheDocument();
    // Retirar sigue pidiendo el motivo: sin él, el botón no se habilita.
    expect(screen.getByRole("button", { name: "Retirar" })).toBeDisabled();
  });

  it("al ganar pide el importe adjudicado en vez de un motivo de pérdida", () => {
    const onConfirmar = vi.fn();
    render(<DialogoCierre pursuit={pursuit} onCancelar={vi.fn()} onConfirmar={onConfirmar} />);

    fireEvent.click(screen.getByRole("button", { name: "Ganada" }));
    expect(screen.queryByRole("combobox", { name: "Motivo del cierre" })).not.toBeInTheDocument();
    const cerrar = screen.getByRole("button", { name: "Confirmar cierre" });
    expect(cerrar).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Importe adjudicado (€)"), {
      target: { value: "2080000" },
    });
    fireEvent.click(cerrar);

    expect(onConfirmar).toHaveBeenCalledWith({
      status: "won",
      outcome: "won",
      awarded_amount_eur: 2080000,
      expected_version: 4,
    });
  });
});
