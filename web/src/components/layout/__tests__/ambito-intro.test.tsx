/**
 * Explicación de primer uso de la barra de ámbito: aparece la primera vez, se
 * cierra con un botón con nombre y no vuelve en ese navegador.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { AmbitoIntro } from "@/components/layout/ambito-intro";

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => cleanup());

const franja = () => screen.queryByRole("complementary", { name: "Qué es el ámbito" });

describe("AmbitoIntro", () => {
  it("se muestra a quien no la ha cerrado nunca", () => {
    render(<AmbitoIntro />);
    expect(franja()).toBeInTheDocument();
    expect(screen.getByText(/filtro común de la consola/)).toBeInTheDocument();
  });

  it("al cerrarla desaparece y se recuerda", () => {
    const { unmount } = render(<AmbitoIntro />);
    fireEvent.click(screen.getByRole("button", { name: "Entendido, no volver a mostrar" }));
    expect(franja()).toBeNull();

    // Otra visita en el mismo navegador: ya no sale.
    unmount();
    render(<AmbitoIntro />);
    expect(franja()).toBeNull();
  });

  it("sobrevive a un localStorage roto sin romper la barra", () => {
    // Clave con JSON inválido: `getJSON` cae al valor por defecto y la franja
    // se muestra en vez de lanzar.
    window.localStorage.setItem("lsap:v1:ambito-intro-vista", "{no-json");
    render(<AmbitoIntro />);
    expect(franja()).toBeInTheDocument();
  });
});
