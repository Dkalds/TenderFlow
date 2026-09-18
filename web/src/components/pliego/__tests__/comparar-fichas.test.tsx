/**
 * F2.8 — comparar fichas del pliego.
 *
 * Se fija: la tabla pinta lo que da la API (una familia vacía se enseña
 * vacía, «no lo publica»); las familias vacías en todos se pliegan pero no
 * desaparecen; los expedientes sin ficha se declaran; y la bandeja admite como
 * mucho tres expedientes, que es el tope del contrato.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { toast } from "sonner";
import { callMethod, callUrl } from "@/hooks/__tests__/fetch-call";
import { ComparacionFichasTabla } from "@/components/pliego/comparar-fichas";
import { BandejaComparacion, CompararBoton } from "@/components/pliego/comparacion-bandeja";
import { useBandejaComparacion } from "@/hooks/use-comparacion";
import { fetchPorRuta, renderConQuery } from "./pliego-render";

const COMPARACION = {
  licitacion_ids: ["A", "B"],
  sin_ficha: ["B"],
  filas: [
    {
      familia: "award_criteria",
      etiqueta: "Criterios de adjudicación",
      vacia_en_todos: false,
      celdas: [
        { licitacion_id: "A", n: 4, ejemplos: ["Precio: 55 puntos", "Metodología"] },
        { licitacion_id: "B", n: 0, ejemplos: [] },
      ],
    },
    {
      familia: "penalties",
      etiqueta: "Penalidades",
      vacia_en_todos: true,
      celdas: [
        { licitacion_id: "A", n: 0, ejemplos: [] },
        { licitacion_id: "B", n: 0, ejemplos: [] },
      ],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  act(() => useBandejaComparacion.setState({ items: [], abierta: false }));
});
afterEach(() => vi.unstubAllGlobals());

describe("ComparacionFichasTabla", () => {
  it("pide la comparación con los ids en el orden elegido y pinta las celdas", async () => {
    const fetch = fetchPorRuta([/comparar$/, COMPARACION]);
    renderConQuery(<ComparacionFichasTabla ids={["A", "B"]} etiquetas={{ A: "Expediente A" }} />);

    expect(await screen.findByText("Precio: 55 puntos")).toBeInTheDocument();
    expect(screen.getByText("y 2 más")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Expediente A" })).toBeInTheDocument();
    expect(screen.getByText("No lo publica")).toBeInTheDocument();
    const llamada = fetch.mock.calls[0];
    expect(callUrl(llamada)).toBe("/api/v1/licitaciones/comparar");
    expect(callMethod(llamada)).toBe("POST");
    expect(JSON.parse(String((llamada[1] as RequestInit).body))).toEqual({ ids: ["A", "B"] });
  });

  it("declara los expedientes sin ficha y pliega —sin omitir— las familias vacías en todos", async () => {
    fetchPorRuta([/comparar$/, COMPARACION]);
    renderConQuery(<ComparacionFichasTabla ids={["A", "B"]} />);

    expect(await screen.findByRole("status")).toHaveTextContent("Sin ficha del pliego extraída todavía: B");
    expect(screen.getByText(/Ningún pliego publica esta familia/)).toBeInTheDocument();
    expect(screen.getByText("Penalidades")).toBeInTheDocument();
    expect(screen.queryByRole("rowheader", { name: "Penalidades" })).not.toBeInTheDocument();
  });

  it("con un solo expediente no pregunta a la API", () => {
    const fetch = fetchPorRuta();
    renderConQuery(<ComparacionFichasTabla ids={["A"]} />);
    expect(screen.getByText("Elige al menos dos expedientes.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("bandeja de comparación", () => {
  it("el botón alterna con aria-pressed y la bandeja aparece con lo marcado", () => {
    render(
      <>
        <CompararBoton id="A" titulo="Expediente A" />
        <BandejaComparacion />
      </>,
    );
    const boton = screen.getByRole("button", { name: "Comparar" });
    expect(boton).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(boton);

    expect(screen.getByRole("button", { name: "En comparación" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Expedientes para comparar" })).toHaveTextContent("Comparar 1/3");
    // Con uno solo no hay nada que comparar todavía.
    expect(screen.getByRole("button", { name: "Comparar fichas" })).toBeDisabled();
  });

  it("no admite un cuarto expediente y lo dice", () => {
    act(() =>
      useBandejaComparacion.setState({
        items: [
          { id: "A", titulo: null },
          { id: "B", titulo: null },
          { id: "C", titulo: null },
        ],
      }),
    );
    render(<CompararBoton id="D" titulo="Cuarto" />);

    fireEvent.click(screen.getByRole("button", { name: "Comparar" }));

    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Ya hay 3 expedientes"));
    expect(useBandejaComparacion.getState().items.map((i) => i.id)).toEqual(["A", "B", "C"]);
  });

  it("con dos marcados abre la tabla de fichas", async () => {
    fetchPorRuta([/comparar$/, COMPARACION]);
    act(() =>
      useBandejaComparacion.setState({
        items: [
          { id: "A", titulo: "Expediente A" },
          { id: "B", titulo: "Expediente B" },
        ],
      }),
    );
    renderConQuery(<BandejaComparacion />);

    fireEvent.click(screen.getByRole("button", { name: "Comparar fichas" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Comparar fichas del pliego");
    expect(await screen.findByText("Precio: 55 puntos")).toBeInTheDocument();
  });
});
