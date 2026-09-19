/**
 * F2.5 — visor de página con la cita resaltada.
 *
 * Se fija: el trozo marcado es el que dicen los offsets **relativos** que da
 * la API; unos offsets que no sirven pintan la página entera con aviso (el
 * criterio de aceptación), y al pasar de página los offsets no viajan — la
 * cita ya no está ahí.
 */
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { callUrl } from "@/hooks/__tests__/fetch-call";
import { PaginaPliegoDialog, trocearResaltado } from "@/components/pliego/pagina-pliego-dialog";
import { fetchPorRuta, renderConQuery } from "./pliego-render";

const CITA = {
  documento_id: 7,
  page_number: 3,
  quote: "peso del 55 %",
  start_offset: 5010,
  end_offset: 5023,
  ocr: false,
};

function pagina(extra: Record<string, unknown> = {}) {
  return {
    documento_id: 7,
    page_number: 3,
    texto: "El precio tendrá un peso del 55 % sobre el total.",
    total_paginas: 12,
    resaltado_inicio: 20,
    resaltado_fin: 33,
    resaltado_omitido: null,
    filename: "PCAP.pdf",
    uri: "https://placsp.example/pcap.pdf",
    ...extra,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("trocearResaltado", () => {
  it("parte el texto por los índices de la página", () => {
    expect(trocearResaltado("abcdef", 2, 4)).toEqual({ antes: "ab", cita: "cd", despues: "ef" });
  });

  it.each([
    ["sin índices", null, null],
    ["invertidos", 4, 2],
    ["vacíos", 3, 3],
    ["fuera del texto", 2, 99],
  ])("con índices %s no marca nada", (_caso, inicio, fin) => {
    expect(trocearResaltado("abcdef", inicio, fin)).toBeNull();
  });
});

describe("PaginaPliegoDialog", () => {
  it("resalta la cita, pide los offsets absolutos y enlaza al original por la página", async () => {
    const fetch = fetchPorRuta([/paginas\/3/, pagina()]);
    renderConQuery(
      <PaginaPliegoDialog licitacionId="LIC/1" cita={CITA} onClose={() => {}} />,
    );

    const marca = await screen.findByText("peso del 55 %");
    expect(marca.tagName).toBe("MARK");
    expect(screen.getByText(/PCAP\.pdf · página 3 de 12/)).toBeInTheDocument();
    expect(callUrl(fetch.mock.calls[0])).toBe(
      "/api/v1/licitaciones/LIC%2F1/documentos/7/paginas/3?inicio=5010&fin=5023",
    );
    expect(screen.getByRole("link", { name: /Abrir el documento original/ })).toHaveAttribute(
      "href",
      "https://placsp.example/pcap.pdf#page=3",
    );
  });

  it("con offsets inválidos enseña la página completa y dice por qué", async () => {
    fetchPorRuta([
      /paginas\/3/,
      pagina({ resaltado_inicio: null, resaltado_fin: null, resaltado_omitido: "offsets_fuera_de_rango" }),
    ]);
    renderConQuery(<PaginaPliegoDialog licitacionId="LIC-1" cita={CITA} onClose={() => {}} />);

    expect(await screen.findByText(/no cae en esta página/)).toBeInTheDocument();
    expect(screen.getByText(/página completa sin resaltar/)).toBeInTheDocument();
    expect(document.querySelector("mark")).toBeNull();
    expect(screen.getByText(/El precio tendrá un peso/)).toBeInTheDocument();
  });

  it("al pasar de página ya no pide resaltado y ofrece volver a la cita", async () => {
    const fetch = fetchPorRuta(
      [/paginas\/4/, pagina({ page_number: 4, texto: "Página siguiente.", resaltado_inicio: null, resaltado_fin: null })],
      [/paginas\/3/, pagina()],
    );
    renderConQuery(<PaginaPliegoDialog licitacionId="LIC-1" cita={CITA} onClose={() => {}} />);
    await screen.findByText("peso del 55 %");

    fireEvent.click(screen.getByRole("button", { name: /Página siguiente/ }));

    await waitFor(() => expect(screen.getByText("Página siguiente.")).toBeInTheDocument());
    const ultima = callUrl(fetch.mock.calls.at(-1)!);
    expect(ultima).toBe("/api/v1/licitaciones/LIC-1/documentos/7/paginas/4");
    expect(screen.getByRole("button", { name: "Volver a la cita" })).toBeInTheDocument();
    // Sin aviso de resaltado fuera de la página de la cita: allí nadie lo pidió.
    expect(screen.queryByText(/sin resaltar/)).not.toBeInTheDocument();
  });

  it("una página sin texto extraído lo dice, sin error genérico", async () => {
    fetchPorRuta([/paginas\/3/, { detail: "No hay texto" }, 404]);
    renderConQuery(<PaginaPliegoDialog licitacionId="LIC-1" cita={CITA} onClose={() => {}} />);

    expect(await screen.findByText("No hay texto extraído para esta página.")).toBeInTheDocument();
  });
});
