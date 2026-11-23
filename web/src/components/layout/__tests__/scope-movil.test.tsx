/**
 * Tests de la barra de ámbito de móvil (`components/layout/scope-movil.tsx`) y
 * su hoja (`hoja-ambito.tsx`).
 *
 * Lo que hay que demostrar: que la fila resume el ámbito sin esconder nada
 * (filtros, recuento y los que no aplican), y que en la hoja está todo lo que
 * la barra de escritorio pone a la vista.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";

vi.mock("@/components/layout/menus-diferidos", () => ({
  VistasDiferidas: () => <button type="button">Vistas</button>,
  ExportarDiferido: ({ label }: { label: string }) => <button type="button">{label}</button>,
}));

import { BarraAmbitoMovil, type BarraAmbitoMovilProps } from "@/components/layout/scope-movil";

// La hoja llega con `next/dynamic` al abrirse.
const DESCARGA = { timeout: 15_000 };

const quitar = vi.fn();
const props = (extra: Partial<BarraAmbitoMovilProps> = {}): BarraAmbitoMovilProps => ({
  chips: [
    { key: "Tecnología", value: "SAP", remove: quitar },
    { key: "CCAA", value: "Madrid", remove: vi.fn() },
  ],
  recuento: "42 licitaciones",
  outOfScopeCount: 0,
  onClearOutOfScope: vi.fn(),
  historial: { canUndo: true, canRedo: false, undo: vi.fn(), redo: vi.fn() },
  editor: <p>editor del ámbito</p>,
  onAbrir: vi.fn(),
  extraExport: {},
  ...extra,
});

const fila = () => screen.getByRole("button", { name: /^Ámbito/ });

afterEach(() => {
  cleanup();
  quitar.mockClear();
});

describe("BarraAmbitoMovil", () => {
  it("resume en una fila los filtros, cuántos son y el recuento, y solo existe por debajo de md", () => {
    render(<BarraAmbitoMovil {...props()} />);
    expect(fila()).toHaveClass("md:hidden");
    expect(fila()).toHaveTextContent("Ámbito2Tecnología SAP · CCAA Madrid42 licitaciones");
  });

  it("sin filtros lo dice, y avisa de los que la pantalla no aplica", () => {
    render(<BarraAmbitoMovil {...props({ chips: [], outOfScopeCount: 1 })} />);
    expect(fila()).toHaveTextContent("Sin filtros · 1 no aplica");
  });

  it("abre una hoja con los chips, el editor, deshacer, vistas, exportar y «Ver»", { timeout: 30_000 }, async () => {
    const onAbrir = vi.fn();
    render(<BarraAmbitoMovil {...props({ onAbrir })} />);
    fireEvent.click(fila());
    expect(onAbrir).toHaveBeenCalled();

    const hoja = await screen.findByRole("dialog", { name: "Ámbito" }, DESCARGA);
    expect(within(hoja).getByText("editor del ámbito")).toBeInTheDocument();
    expect(within(hoja).getByRole("button", { name: "Deshacer cambio de ámbito" })).toBeEnabled();
    expect(within(hoja).getByRole("button", { name: "Rehacer cambio de ámbito" })).toBeDisabled();
    for (const nombre of ["Vistas", "Exportar"]) {
      expect(within(hoja).getByRole("button", { name: nombre })).toBeInTheDocument();
    }

    fireEvent.click(within(hoja).getByRole("button", { name: "Quitar tecnología SAP" }));
    expect(quitar).toHaveBeenCalled();

    fireEvent.click(within(hoja).getByRole("button", { name: "Ver 42 licitaciones" }));
    expect(fila()).toHaveAttribute("aria-expanded", "false");
  });

  it("mientras llega el recuento, «Ver» no inventa un número", { timeout: 30_000 }, async () => {
    render(<BarraAmbitoMovil {...props({ recuento: "—" })} />);
    fireEvent.click(fila());
    const hoja = await screen.findByRole("dialog", { name: "Ámbito" }, DESCARGA);
    expect(within(hoja).getByRole("button", { name: "Ver resultados" })).toBeInTheDocument();
  });
});
