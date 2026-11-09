import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GlosarioHint } from "../glosario-hint";

vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

/** En el móvil no hay hover: pulsar el «?» tiene que enseñar la definición. */
describe("GlosarioHint", () => {
  it("se abre y se cierra pulsándolo", async () => {
    render(
      <TooltipProvider>
        <GlosarioHint termino="ADJ" />
      </TooltipProvider>,
    );
    const boton = screen.getByRole("button", { name: /Qué es/ });

    fireEvent.click(boton);
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();

    fireEvent.click(boton);
    await vi.waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });
});
