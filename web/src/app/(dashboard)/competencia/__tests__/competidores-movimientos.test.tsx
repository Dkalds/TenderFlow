/**
 * La tarjeta de vigiladas: la lista de empresas y sus señales.
 *
 * Fija que la lista se pinta —hasta 2026-09-25 sólo se contaba—, que cada
 * empresa lleva a su ficha y que la falta de señales no esconde la lista.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Schemas } from "@/lib/api-types";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiGet }));

import { CompetidoresMovimientos } from "../_components/competidores-movimientos";

type Movimientos = Schemas["MovimientosVigiladasResult"];

const EMPRESAS: Movimientos["empresas"] = [
  { empresa_id: 7, nombre: "Ejemplo Digital", adjudicaciones: 3, importe: 1_200_000 },
  { empresa_id: 8, nombre: "Norte Sistemas", adjudicaciones: 1, importe: 90_000 },
  { empresa_id: 9, nombre: "Sur Consultoría", adjudicaciones: 0, importe: 0 },
];

function renderTarjeta(movimientos: Partial<Movimientos>) {
  apiGet.mockResolvedValue({ desde: "2026-08-26", dias: 30, senales_truncadas: false, ...movimientos });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompetidoresMovimientos />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
});

describe("CompetidoresMovimientos", () => {
  it("lista las vigiladas, cada una hacia su ficha y con lo que ha ganado", async () => {
    renderTarjeta({ empresas: EMPRESAS, senales: [] });

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
    renderTarjeta({ empresas: EMPRESAS, senales: [] });

    expect(await screen.findByText("Sin movimientos destacables en este periodo.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(EMPRESAS!.length);
  });

  it("las señales van debajo de la lista, con su licitación", async () => {
    renderTarjeta({
      empresas: EMPRESAS,
      senales: [
        {
          tipo: "nueva_ccaa",
          empresa_id: 7,
          empresa: "Ejemplo Digital",
          titulo: "Ejemplo Digital entra en Galicia",
          detalle: "Primera adjudicación en Galicia: Servicio de soporte.",
          licitacion_id: "LIC-1",
          fecha: "2026-09-10",
          importe: 400_000,
        },
      ],
    });

    expect(await screen.findByText("Ejemplo Digital entra en Galicia")).toBeInTheDocument();
    expect(screen.getByText("Territorio nuevo")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver la licitación LIC-1" })).toHaveAttribute("href", "/detalle?lic=LIC-1");
  });

  it("sin vigiladas explica cómo empezar a vigilar", async () => {
    renderTarjeta({ empresas: [], senales: [] });

    expect(await screen.findByText(/No vigilas ninguna empresa/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Empresas vigiladas" })).not.toBeInTheDocument();
  });
});
