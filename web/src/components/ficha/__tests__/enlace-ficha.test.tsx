/**
 * CU-02 — abrir la ficha de una licitación sin salir de la lista
 * (`enlace-ficha.tsx`).
 *
 * El clic normal abre el panel (`?ver=` con `pushState`, sin navegar); el que
 * lleva Ctrl/⌘ sigue al `href` de siempre, y en `/detalle`, donde `?lic=` ya
 * abre su inspector, el enlace navega como antes.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { EnlaceFicha } from "../enlace-ficha";

function pulsar(init: MouseEventInit = {}) {
  render(<EnlaceFicha idExterno="EXP 1/2026">Mantenimiento SAP</EnlaceFicha>);
  const enlace = screen.getByRole("link", { name: "Mantenimiento SAP" });
  // `fireEvent.click` devuelve `false` si alguien llamó a `preventDefault`.
  return { enlace, siguio: fireEvent.click(enlace, init) };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/resumen?ambito=madrid");
});

afterEach(cleanup);

describe("EnlaceFicha", () => {
  it("abre la ficha en el panel sin salir de la pantalla ni perder su URL", () => {
    const { enlace, siguio } = pulsar();

    expect(enlace).toHaveAttribute("href", "/detalle?lic=EXP%201%2F2026");
    expect(siguio).toBe(false);
    expect(window.location.pathname).toBe("/resumen");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("ver")).toBe("EXP 1/2026");
    expect(params.get("ambito")).toBe("madrid");
  });

  it("con Ctrl o ⌘ deja al navegador abrir la ficha de siempre", () => {
    expect(pulsar({ ctrlKey: true }).siguio).toBe(true);
    cleanup();
    expect(pulsar({ metaKey: true }).siguio).toBe(true);
    expect(new URLSearchParams(window.location.search).get("ver")).toBeNull();
  });

  it("en /detalle navega como antes: allí `?lic=` abre el inspector", () => {
    window.history.replaceState(null, "", "/detalle");

    expect(pulsar().siguio).toBe(true);
    expect(new URLSearchParams(window.location.search).get("ver")).toBeNull();
  });
});
