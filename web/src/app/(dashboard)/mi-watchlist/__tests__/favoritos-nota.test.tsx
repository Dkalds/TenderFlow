/**
 * La nota personal del favorito en la pestaña Favoritos (CU-03).
 *
 * Se doblan los hooks: lo que se fija aquí es lo que la fila enseña y qué
 * manda al guardar. El PUT y su optimismo están en
 * `hooks/__tests__/use-watchlist-items.test.ts`.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";

const { mutate, items } = vi.hoisted(() => ({
  mutate: vi.fn(),
  items: {
    lista: [] as Array<Record<string, unknown>>,
  },
}));

vi.mock("@/hooks/use-watchlist-items", () => ({
  MAX_NOTA_FAVORITO: 2000,
  useWatchlistItems: () => ({ data: items.lista, isLoading: false }),
  useRemoveWatchlistItem: () => ({ mutate: vi.fn() }),
  useSetWatchlistNota: () => ({ mutate, isPending: false }),
}));
vi.mock("@/hooks/use-etiquetas", () => ({ useEtiquetasDe: () => ({ data: {} }) }));
vi.mock("@/components/etiquetas/etiquetas-objeto", () => ({
  EtiquetaChips: () => null,
  EtiquetasEditor: () => null,
}));
vi.mock("@/components/pliego/comparacion-bandeja", () => ({ CompararBoton: () => null }));

import { FavoritosPanel } from "../_components/favoritos-panel";

function favorito(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    id_externo: "EXP-1",
    created_at: "2026-09-01T00:00:00Z",
    organization_id: 3,
    visibility: "private",
    nota: null,
    titulo: "Implantación SAP",
    importe: 1000,
    estado: "PUB",
    fecha_publicacion: "2026-09-01",
    ...over,
  };
}

function pintar() {
  return render(
    <TooltipProvider>
      <FavoritosPanel />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  mutate.mockClear();
});

describe("Nota del favorito", () => {
  it("enseña la nota bajo el título", () => {
    items.lista = [favorito({ nota: "Llamar al cliente el lunes" })];
    pintar();

    expect(screen.getByText("Llamar al cliente el lunes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar la nota" })).toBeInTheDocument();
  });

  it("se escribe en la propia fila, con contador, y se guarda", () => {
    items.lista = [favorito()];
    pintar();

    fireEvent.click(screen.getByRole("button", { name: "Añadir una nota" }));
    const campo = screen.getByRole("textbox", { name: /Nota sobre Implantación SAP/ });
    expect(campo).toHaveFocus();
    expect(campo).toHaveAttribute("maxLength", "2000");
    fireEvent.change(campo, { target: { value: "Pedir aclaración del lote 2" } });
    expect(screen.getByText("27 / 2000")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Guardar nota" }));

    expect(mutate).toHaveBeenCalledWith({ idExterno: "EXP-1", nota: "Pedir aclaración del lote 2" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("cancelar no guarda nada y Escape también cierra", () => {
    items.lista = [favorito({ nota: "Original" })];
    pintar();

    fireEvent.click(screen.getByRole("button", { name: "Editar la nota" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Cambiada" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Original")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar la nota" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Editar la nota" }));
    // El editor vuelve a abrir con la nota vigente, no con el borrador cancelado.
    expect(screen.getByRole("textbox")).toHaveValue("Original");
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("vaciar una nota existente la borra", () => {
    items.lista = [favorito({ nota: "Sobra" })];
    pintar();

    fireEvent.click(screen.getByRole("button", { name: "Editar la nota" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Borrar nota" }));

    expect(mutate).toHaveBeenCalledWith({ idExterno: "EXP-1", nota: "" });
  });
});
