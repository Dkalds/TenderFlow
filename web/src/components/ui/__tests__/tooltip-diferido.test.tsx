/**
 * El tooltip pinta primero un disparador provisional y monta Radix cuando su
 * módulo llega (`components/ui/tooltip.tsx`). El resto de la suite lo precarga
 * en `src/test/setup.ts`; aquí cada prueba importa el módulo de nuevo, sin el
 * Radix cargado, para fijar lo que el cambio no puede romper: el foco y el clic.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type ModuloTooltip = typeof import("@/components/ui/tooltip");
let t: ModuloTooltip;

beforeEach(async () => {
  vi.resetModules();
  t = await import("@/components/ui/tooltip");
});
afterEach(() => cleanup());

function pintar() {
  const { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } = t;
  render(
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button">Exportar</button>
        </TooltipTrigger>
        <TooltipContent>Descarga la vista en CSV</TooltipContent>
      </Tooltip>
    </TooltipProvider>,
  );
  return screen.getByRole("button", { name: "Exportar" });
}

describe("Tooltip diferido", () => {
  it("antes de llegar Radix pinta el disparador cerrado y ningún contenido", () => {
    const boton = pintar();
    expect(boton).toHaveAttribute("data-state", "closed");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("si el foco llegó con el teclado, el disparador real lo recoge y abre el tooltip", async () => {
    const provisional = pintar();
    act(() => provisional.focus());

    expect(await screen.findByRole("tooltip")).toHaveTextContent("Descarga la vista en CSV");
    const real = screen.getByRole("button", { name: "Exportar" });
    expect(real).not.toBe(provisional);
    expect(real).toHaveFocus();
  });

  it("si el foco llegó de un clic, lo conserva sin abrir el tooltip", async () => {
    const provisional = pintar();
    fireEvent.pointerDown(provisional);
    act(() => provisional.focus());
    await act(() => t.cargarTooltip());
    fireEvent.pointerUp(window);

    await waitFor(() => expect(screen.getByRole("button", { name: "Exportar" })).not.toBe(provisional));
    expect(screen.getByRole("button", { name: "Exportar" })).toHaveFocus();
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("con el botón del puntero pulsado no cambia el nodo: el clic no se parte en dos", async () => {
    const alPulsar = vi.fn();
    const { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } = t;
    render(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" onClick={alPulsar}>
              Guardar
            </button>
          </TooltipTrigger>
          <TooltipContent>Guarda la vista</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    const provisional = screen.getByRole("button", { name: "Guardar" });

    fireEvent.pointerDown(provisional);
    await act(() => t.cargarTooltip());
    expect(screen.getByRole("button", { name: "Guardar" })).toBe(provisional);

    fireEvent.click(provisional);
    expect(alPulsar).toHaveBeenCalledOnce();
    fireEvent.pointerUp(window);
    await waitFor(() => expect(screen.getByRole("button", { name: "Guardar" })).not.toBe(provisional));
  });

  it("sin TooltipProvider lanza, como Radix", () => {
    const { Tooltip, TooltipTrigger } = t;
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(
        <Tooltip>
          <TooltipTrigger>x</TooltipTrigger>
        </Tooltip>,
      ),
    ).toThrow(/TooltipProvider/);
  });
});
