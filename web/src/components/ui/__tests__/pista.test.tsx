/**
 * `Pista` sustituye a `title=` en texto y celdas. Lo que tiene que garantizar
 * es lo que justifica que exista en vez de un `TooltipTrigger` normal: que el
 * elemento **no** se vuelva focusable (una tabla no puede ganar una parada de
 * tabulación por celda) y que sin contenido no monte nada.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { Pista } from "@/components/ui/pista";
import { TooltipProvider } from "@/components/ui/tooltip";

afterEach(() => cleanup());

function conProveedor(ui: React.ReactElement) {
  return render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>);
}

describe("Pista", () => {
  it("engancha el elemento como disparador sin volverlo focusable", () => {
    conProveedor(
      <Pista contenido="Órgano de contratación completo">
        <span>Órgano de contrat…</span>
      </Pista>,
    );

    const texto = screen.getByText("Órgano de contrat…");
    // Es el disparador (Radix le pone su estado)…
    expect(texto).toHaveAttribute("data-state", "closed");
    // …pero sigue fuera del orden de tabulación: ni `tabindex` ni botón.
    expect(texto).not.toHaveAttribute("tabindex");
    expect(texto.tabIndex).toBe(-1);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([null, undefined, ""])("sin contenido (%s) devuelve el hijo tal cual", (contenido) => {
    // Sin proveedor a propósito: si montara un `Tooltip`, Radix lanzaría.
    render(
      <Pista contenido={contenido}>
        <span>sin pista</span>
      </Pista>,
    );
    expect(screen.getByText("sin pista")).not.toHaveAttribute("data-state");
  });
});
