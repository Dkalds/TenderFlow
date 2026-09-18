/**
 * F2.6 — guion de la oferta técnica.
 *
 * Se fija: no se genera al montar (cuesta presupuesto de LLM), un punto sin
 * cita se ve marcado y no escondido, cada cita abre su página, el 429 dice
 * que el presupuesto se agotó, y el Markdown cita documento y página —no el
 * texto citado—, igual que el export del backend.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento: vi.fn(),
}));

import { registrarEvento } from "@/lib/analytics";
import { callMethod, callUrl } from "@/hooks/__tests__/fetch-call";
import { GuionOfertaPanel } from "@/components/pliego/guion-oferta";
import { guionAMarkdown, type GuionOferta } from "@/hooks/use-guion-oferta";
import { fetchPorRuta, renderConQuery } from "./pliego-render";

const GUION: GuionOferta = {
  licitacion_id: "LIC-1",
  firma: "abc",
  sin_guion: null,
  criterios: [
    {
      criterio: "Metodología",
      peso_pct: 30,
      puntos: [
        {
          texto: "Plan de migración por fases.",
          sin_base: false,
          evidencia: [{ documento_id: 7, page_number: 4, quote: "migración", ocr: false }],
        },
        { texto: "Oficina de proyecto con PMO propia.", sin_base: true, evidencia: [] },
      ],
    },
  ],
};

const DOCUMENTOS = { id_externo: "LIC-1", items: [{ id: 7, tipo: "legal", uri: "u", status: "extracted", filename: "PPT.pdf" }] };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("GuionOfertaPanel", () => {
  it("no genera nada hasta que se pide", () => {
    const fetch = fetchPorRuta([/documentos$/, DOCUMENTOS]);
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);

    expect(screen.getByRole("button", { name: "Generar guion" })).toBeInTheDocument();
    expect(fetch.mock.calls.some((c) => callUrl(c).includes("/guion"))).toBe(false);
  });

  it("genera con POST, marca los puntos sin base y cuenta el uso por tramos", async () => {
    const fetch = fetchPorRuta([/\/guion$/, GUION], [/documentos$/, DOCUMENTOS]);
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));

    expect(await screen.findByText("Plan de migración por fases.")).toBeInTheDocument();
    const llamada = fetch.mock.calls.find((c) => callUrl(c).endsWith("/guion"))!;
    expect(callMethod(llamada)).toBe("POST");
    expect(screen.getByText("Sin base en el pliego")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "PPT.pdf · p. 4" })).toBeInTheDocument();
    expect(registrarEvento).toHaveBeenCalledWith("guion_generado", { criterios: "1-3" });
  });

  it("una cita del guion abre la página del pliego", async () => {
    fetchPorRuta(
      [/\/guion$/, GUION],
      [/documentos$/, DOCUMENTOS],
      [/paginas\/4/, { documento_id: 7, page_number: 4, texto: "Texto de la página cuatro.", total_paginas: 9 }],
    );
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));

    fireEvent.click(await screen.findByRole("button", { name: "PPT.pdf · p. 4" }));

    expect(await screen.findByText("Texto de la página cuatro.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveTextContent("PPT.pdf · página 4 de 9");
    // La cita del guion no trae offsets: se dice, en vez de fingir un resaltado.
    expect(screen.getByRole("dialog")).toHaveTextContent("La cita no guarda su posición");
  });

  it("un pliego sin criterios dice por qué y no cuenta como uso", async () => {
    fetchPorRuta(
      [/\/guion$/, { licitacion_id: "LIC-1", criterios: [], sin_guion: "El pliego no publica criterios." }],
      [/documentos$/, DOCUMENTOS],
    );
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));

    expect(await screen.findByText("El pliego no publica criterios.")).toBeInTheDocument();
    expect(registrarEvento).not.toHaveBeenCalled();
  });

  it("el 429 dice que el presupuesto de IA se agotó", async () => {
    fetchPorRuta([/\/guion$/, { detail: "Tope mensual alcanzado" }, 429], [/documentos$/, DOCUMENTOS]);
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Presupuesto de IA agotado: Tope mensual alcanzado",
    );
  });
});

describe("guionAMarkdown", () => {
  it("es un esquema por criterio con referencias, no con el texto citado", () => {
    const md = guionAMarkdown(GUION, () => "PPT.pdf");
    expect(md).toContain("## Metodología (30 puntos)");
    expect(md).toContain("- Plan de migración por fases. _(PPT.pdf p. 4)_");
    expect(md).toContain("- Oficina de proyecto con PMO propia. _[sin base en el pliego]_");
    expect(md).not.toContain("migración»");
  });
});
