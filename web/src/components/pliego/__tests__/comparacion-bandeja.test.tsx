/**
 * F2.8 — la bandeja de comparación y su pregunta cruzada.
 *
 * Hasta 2026-10 el diálogo de comparación tenía su propio chat debajo de la
 * tabla, con su conversación. Hoy pregunta al asistente único: el botón lo abre
 * con los expedientes de la bandeja como contexto y cierra el diálogo, que es
 * modal y no dejaría escribir en el asistente. La tabla sigue a un clic en la
 * bandeja.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/components/pliego/comparar-fichas", () => ({
  ComparacionFichasTabla: () => <p>tabla de fichas</p>,
}));

import { BandejaComparacion } from "@/components/pliego/comparacion-bandeja";
import { useBandejaComparacion } from "@/hooks/use-comparacion";
import { useAsistente } from "@/lib/asistente-store";

beforeEach(() => {
  useAsistente.getState().reiniciar();
  act(() => {
    useBandejaComparacion.getState().vaciar();
    useBandejaComparacion.getState().alternar({ id: "A", titulo: "Mantenimiento SAP" });
    useBandejaComparacion.getState().alternar({ id: "B", titulo: "Soporte Oracle" });
  });
});
afterEach(cleanup);

describe("BandejaComparacion", () => {
  it("pregunta sobre los expedientes de la bandeja en el asistente, y le deja sitio", async () => {
    render(<BandejaComparacion />);
    fireEvent.click(screen.getByRole("button", { name: "Comparar fichas" }));
    expect(await screen.findByText("tabla de fichas")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Preguntar al asistente sobre estos 2 expedientes" }));

    expect(useBandejaComparacion.getState().abierta).toBe(false);
    const estado = useAsistente.getState();
    expect(estado.abierto).toBe(true);
    expect(estado.contexto).toEqual({
      expedientes: [
        { id: "A", titulo: "Mantenimiento SAP" },
        { id: "B", titulo: "Soporte Oracle" },
      ],
      origen: "comparacion",
    });
  });
});
