/**
 * El panel de vigiladas: un carril por empresa y sus señales.
 *
 * Fija que la lista se pinta, que cada empresa lleva a su ficha, que la falta
 * de señales no esconde la lista y que el carril dice a quien no lo ve lo mismo
 * que dibuja.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Schemas } from "@/lib/api-types";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiGet }));

import { CompetidoresVigilados } from "../_components/competidores-vigilados";

type Movimientos = Schemas["MovimientosVigiladasResult"];

const EMPRESAS: Movimientos["empresas"] = [
  { empresa_id: 7, nombre: "Ejemplo Digital", adjudicaciones: 3, importe: 1_200_000 },
  { empresa_id: 8, nombre: "Norte Sistemas", adjudicaciones: 1, importe: 90_000 },
  { empresa_id: 9, nombre: "Sur Consultoría", adjudicaciones: 0, importe: 0 },
];

const ENTRADA_EN_GALICIA: NonNullable<Movimientos["senales"]>[number] = {
  tipo: "nueva_ccaa",
  empresa_id: 7,
  empresa: "Ejemplo Digital",
  titulo: "Ejemplo Digital entra en Galicia",
  detalle: "Primera adjudicación en Galicia: Servicio de soporte.",
  licitacion_id: "LIC-1",
  fecha: "2026-09-10",
  importe: 400_000,
};

function renderPanel(movimientos: Partial<Movimientos>) {
  apiGet.mockResolvedValue({ desde: "2026-08-26", dias: 30, senales_truncadas: false, ...movimientos });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompetidoresVigilados />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
});

describe("CompetidoresVigilados", () => {
  it("lista las vigiladas, cada una hacia su ficha y con lo que ha ganado", async () => {
    renderPanel({ empresas: EMPRESAS, senales: [] });

    const lista = await screen.findByRole("list", { name: "Empresas vigiladas" });
    expect(within(lista).getByRole("link", { name: "Ejemplo Digital" })).toHaveAttribute(
      "href",
      "/competencia/empresa/7",
    );
    expect(within(lista).getByText(/^3 adjudicaciones · 1\.200\.000/)).toBeInTheDocument();
    expect(within(lista).getByText(/^1 adjudicación · 90\.000/)).toBeInTheDocument();
    // La que no se ha movido sigue en la lista: se vigila igual.
    expect(within(lista).getByRole("link", { name: "Sur Consultoría" })).toBeInTheDocument();
    expect(within(lista).getByText("sin adjudicaciones")).toBeInTheDocument();
  });

  it("sin señales lo dice, pero la lista se queda", async () => {
    renderPanel({ empresas: EMPRESAS, senales: [] });

    expect(await screen.findByText("Sin movimientos destacables en este periodo.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(EMPRESAS!.length);
  });

  it("el carril de cada empresa dice sus movimientos fechados", async () => {
    renderPanel({ empresas: EMPRESAS, senales: [ENTRADA_EN_GALICIA] });

    // Quien no ve la marca en el carril lee lo mismo: qué pasó y cuándo.
    expect(await screen.findByRole("img", { name: /^Ejemplo Digital: Territorio nuevo el / })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Norte Sistemas: sin movimientos fechados en la ventana" })).toBeInTheDocument();
  });

  it("las señales van debajo de la lista, con su licitación", async () => {
    renderPanel({ empresas: EMPRESAS, senales: [ENTRADA_EN_GALICIA] });

    const movimientos = await screen.findByRole("list", { name: "Movimientos" });
    expect(within(movimientos).getByText("Ejemplo Digital entra en Galicia")).toBeInTheDocument();
    expect(within(movimientos).getByText("Territorio nuevo")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver la licitación LIC-1" })).toHaveAttribute("href", "/detalle?lic=LIC-1");
  });

  it("la ventana es la que manda la API, no una constante de la pantalla", async () => {
    renderPanel({ dias: 45, empresas: EMPRESAS, senales: [] });

    expect(await screen.findByText("últimos 45 días, sobre adjudicaciones")).toBeInTheDocument();
  });

  it("sin vigiladas explica cómo empezar a vigilar", async () => {
    renderPanel({ empresas: [], senales: [] });

    expect(await screen.findByText(/No vigilas ninguna empresa/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Empresas vigiladas" })).not.toBeInTheDocument();
  });
});
