/**
 * El disparador provisional de un menú diferido: lo que se hace con él antes
 * de que llegue el módulo real no se pierde (abrir, y con qué) y el foco pasa
 * al disparador real.
 */
import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Diferido, type MontajeDiferido, useMontajeDiferido } from "@/components/ui/carga-diferida";

function Real(montaje: MontajeDiferido) {
  const { disparador, abiertoAlMontar } = useMontajeDiferido(montaje);
  return (
    <button ref={disparador} type="button" data-abierto={String(abiertoAlMontar)} data-con={montaje.abrirAlMontar}>
      real
    </button>
  );
}

const cargar = () => Promise.resolve(Real);

function montar(abreCon: "pulsar" | "clic" = "pulsar") {
  render(
    <Diferido
      cargar={cargar}
      props={{}}
      abreCon={abreCon}
      disparador={(eventos) => (
        <button type="button" {...eventos}>
          provisional
        </button>
      )}
    />,
  );
  return screen.getByRole("button", { name: "provisional" });
}

describe("Diferido", () => {
  it("abrir con el teclado antes de que llegue lo monta abierto, y dice con qué", async () => {
    fireEvent.keyDown(montar(), { key: "ArrowDown" });
    const real = await screen.findByRole("button", { name: "real" });
    expect(real).toHaveAttribute("data-abierto", "true");
    expect(real).toHaveAttribute("data-con", "teclado");
  });

  it("un menú abre al pulsar con el puntero", async () => {
    fireEvent.pointerDown(montar(), { button: 0 });
    expect(await screen.findByRole("button", { name: "real" })).toHaveAttribute("data-con", "puntero");
  });

  it("un popover no abre al pulsar, sino con el clic", async () => {
    const provisional = montar("clic");
    fireEvent.pointerDown(provisional, { button: 0 });
    fireEvent.click(provisional, { detail: 1 });
    expect(await screen.findByRole("button", { name: "real" })).toHaveAttribute("data-con", "puntero");
  });

  it("si el provisional tenía el foco, lo recoge el real", async () => {
    const provisional = montar();
    act(() => provisional.focus());
    const real = await screen.findByRole("button", { name: "real" });
    expect(real).toHaveAttribute("data-abierto", "false");
    // El foco lo pasa un efecto del disparador real, que React ejecuta después
    // de montarlo: con el runner cargado, leerlo en el acto lo encontraba aún en
    // `body` (CI del 2026-11-13).
    await waitFor(() => expect(real).toHaveFocus());
  });
});
