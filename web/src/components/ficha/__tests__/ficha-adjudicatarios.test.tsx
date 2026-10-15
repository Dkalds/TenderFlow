import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FichaAdjudicatarios } from "@/components/ficha/ficha-adjudicatarios";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

const base: LicitacionDetail = {
  id_externo: "EXP-1",
  titulo: "Servicios TI en dos lotes",
  organo_contratacion: "Ayuntamiento de Getafe",
  importe: 300000,
  estado: "ADJ",
  fecha_publicacion: "2026-03-01",
  ccaa: "Madrid",
  cpv: "72267100",
  url: null,
  fuente: "placsp",
  tecnologia: "SAP",
  tipo_contrato: "2",
  provincia: "Madrid",
  fecha_limite: null,
  fecha_inicio: null,
  fecha_fin: null,
  descripcion: null,
};

afterEach(cleanup);

describe("FichaAdjudicatarios", () => {
  it("dice quién ganó cada lote, con NIF, importe y ofertas", () => {
    render(
      <FichaAdjudicatarios
        licitacion={{
          ...base,
          adjudicatarios: [
            {
              nombre: "Integra SL",
              nif: "B12345678",
              importe_adjudicado: 80000,
              n_ofertas_recibidas: 3,
              fecha_adjudicacion: "2026-10-01",
              lote_numero: "1",
              lote_titulo: "Mantenimiento",
            },
            {
              nombre: "Consultora Norte SA",
              nif: null,
              importe_adjudicado: null,
              n_ofertas_recibidas: null,
              fecha_adjudicacion: null,
              lote_numero: "2",
              lote_titulo: null,
            },
          ],
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Adjudicación" })).toBeInTheDocument();
    expect(screen.getByText("Integra SL")).toBeInTheDocument();
    expect(screen.getByText("B12345678")).toBeInTheDocument();
    expect(screen.getByText(/Lote 1 · Mantenimiento/)).toBeInTheDocument();
    expect(screen.getByText(/3 ofertas/)).toBeInTheDocument();
    // Lo que la fuente no publicó se dice, no se rellena con un cero.
    expect(screen.getByText(/Lote 2 · importe no publicado · ofertas no publicadas/)).toBeInTheDocument();
  });

  it("una sola oferta va en singular", () => {
    render(
      <FichaAdjudicatarios
        licitacion={{
          ...base,
          adjudicatarios: [
            {
              nombre: "Única SL",
              nif: null,
              importe_adjudicado: 1000,
              n_ofertas_recibidas: 1,
              fecha_adjudicacion: null,
              lote_numero: null,
              lote_titulo: null,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/1 oferta(?!s)/)).toBeInTheDocument();
  });

  it("adjudicado sin adjudicatario publicado lo dice; abierto no pinta nada", () => {
    const { container, rerender } = render(<FichaAdjudicatarios licitacion={{ ...base, adjudicatarios: [] }} />);
    expect(screen.getByText("La fuente no ha publicado el adjudicatario")).toBeInTheDocument();

    rerender(<FichaAdjudicatarios licitacion={{ ...base, estado: "PUB", adjudicatarios: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
