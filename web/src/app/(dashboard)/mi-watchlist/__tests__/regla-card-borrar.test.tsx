/**
 * Eliminar una regla pide confirmación en la tarjeta: borrar no se deshace, y
 * la alerta por defecto no vuelve a crearse. Si es la única activa, avisa de
 * que con ella se va el resumen diario y ofrece desactivarla en su lugar.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ReglaCard } from "@/app/(dashboard)/mi-watchlist/_components/regla-card";
import type { ApiRule } from "@/app/(dashboard)/mi-watchlist/_hooks/watchlist-rule-types";

const RULE = {
  id: 42,
  nombre: "SAP",
  keyword: "SAP",
  cpv: null,
  min_importe: null,
  ccaa: null,
  frequency: "daily",
  active: true,
  match_count: 7,
  email: null,
} as ApiRule;

function montar(ultimaActiva: boolean) {
  const onDelete = vi.fn();
  const onUpdate = vi.fn();
  render(
    <TooltipProvider>
      <ReglaCard rule={RULE} ultimaActiva={ultimaActiva} onUpdate={onUpdate} onEdit={vi.fn()} onDelete={onDelete} />
    </TooltipProvider>,
  );
  return { onDelete, onUpdate };
}

describe("ReglaCard · eliminar", () => {
  it("no borra al primer clic: pide confirmación y Cancelar la retira", () => {
    const { onDelete } = montar(false);

    fireEvent.click(screen.getByRole("button", { name: "Eliminar regla" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Eliminarla no se puede deshacer.");

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("confirmar borra la regla", () => {
    const { onDelete } = montar(false);

    fireEvent.click(screen.getByRole("button", { name: "Eliminar regla" }));
    fireEvent.click(screen.getByRole("button", { name: "Sí, eliminar" }));

    expect(onDelete).toHaveBeenCalledWith(42);
  });

  it("si es la única activa avisa del resumen y deja desactivarla en vez de borrarla", () => {
    const { onDelete, onUpdate } = montar(true);

    fireEvent.click(screen.getByRole("button", { name: "Eliminar regla" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Es tu única regla activa");
    expect(screen.getByRole("alert")).toHaveTextContent("resumen diario");

    fireEvent.click(screen.getByRole("button", { name: "Desactivar" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(onUpdate).toHaveBeenCalledWith(42, expect.objectContaining({ active: false }));
  });
});
