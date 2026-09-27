/**
 * Diálogo: capa modal con la escala de elevación de la casa (scrim único al
 * 50 %, superficie opaca, radio de superficie y sombra de modal).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";

function Abierto() {
  return (
    <Dialog open>
      <DialogContent>
        <DialogTitle>Comparar</DialogTitle>
        <DialogDescription>Dos expedientes</DialogDescription>
      </DialogContent>
    </Dialog>
  );
}

describe("Dialog", () => {
  it("se anuncia como diálogo con su título y se cierra con un botón en castellano", () => {
    render(<Abierto />);
    expect(screen.getByRole("dialog", { name: "Comparar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cerrar" })).toBeInTheDocument();
  });

  it("el scrim es el mismo que el de la hoja: negro al 50 %", () => {
    render(<Abierto />);
    expect(document.querySelector(".fixed.inset-0.bg-black\\/50")).toBeInTheDocument();
  });

  it("superficie opaca, radio de superficie y sombra de modal", () => {
    render(<Abierto />);
    const dialogo = screen.getByRole("dialog");
    expect(dialogo).toHaveClass("bg-popover", "rounded-xl", "shadow-lg");
    expect(dialogo.className).not.toMatch(/tf-glass/);
  });

  it("el título va a 15 px", () => {
    render(<Abierto />);
    expect(screen.getByText("Comparar")).toHaveClass("text-tf-lede");
  });
});
