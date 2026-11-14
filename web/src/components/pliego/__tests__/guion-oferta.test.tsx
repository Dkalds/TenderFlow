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

vi.mock("@/lib/export", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/export")>()),
  descargarBlob: vi.fn(),
}));

import { registrarEvento } from "@/lib/analytics";
import { descargarBlob } from "@/lib/export";
import { callMethod, callUrl } from "@/hooks/__tests__/fetch-call";
import { GuionOfertaPanel } from "@/components/pliego/guion-oferta";
import { guionAMarkdown, type GuionOferta } from "@/hooks/use-guion-oferta";
import { useOrganizationStore } from "@/lib/organization-store";
import { fetchPorRuta, renderConQuery } from "./pliego-render";

const GUION: GuionOferta = {
  licitacion_id: "LIC-1",
  firma: "abc",
  sin_guion: null,
  citas_organizacion_fallidas: false,
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

  it("enseña bajo cada criterio lo que la organización ya escribió, rotulado y aparte de los puntos", async () => {
    const propia = {
      attachment_id: 11,
      filename: "Memoria técnica.pdf",
      page_number: 12,
      cita: "La migración se organiza en tres oleadas de carga.",
      pursuit_id: 42,
      licitacion_id: "EXP-9",
      licitacion_titulo: "Migración del ERP provincial",
    };
    const conCitas = { ...GUION, criterios: [{ ...GUION.criterios![0], citas_organizacion: [propia] }] };
    fetchPorRuta([/\/guion$/, conCitas], [/documentos$/, DOCUMENTOS]);
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));

    expect(await screen.findByText("De documentos de tu organización (1)")).toBeInTheDocument();
    expect(screen.getByText("Memoria técnica.pdf, p. 12")).toBeInTheDocument();
    expect(screen.getByText("La migración se organiza en tres oleadas de carga.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Oportunidad: Migración del ERP provincial" })).toHaveAttribute(
      "href",
      "/oportunidades/42",
    );
  });

  it("si no se pudieron consultar los documentos propios, lo dice en vez de callar", async () => {
    fetchPorRuta([/\/guion$/, { ...GUION, citas_organizacion_fallidas: true }], [/documentos$/, DOCUMENTOS]);
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));

    expect(await screen.findByText(/No se pudieron consultar los documentos de tu organización/)).toBeInTheDocument();
    expect(screen.queryByText(/De documentos de tu organización/)).not.toBeInTheDocument();
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

describe("GuionOfertaPanel · PDF", () => {
  it("descarga el PDF del guion ya generado, con GET y sin volver a generar", async () => {
    const descargar = vi.mocked(descargarBlob);
    const fetch = fetchPorRuta(
      [/guion\.pdf$/, { ok: true }],
      [/\/guion$/, GUION],
      [/documentos$/, DOCUMENTOS],
    );
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));
    fireEvent.click(await screen.findByRole("button", { name: "Descargar PDF" }));

    await vi.waitFor(() => expect(descargar).toHaveBeenCalled());
    const pdf = fetch.mock.calls.find((c) => callUrl(c).endsWith("/guion.pdf"))!;
    expect(callMethod(pdf)).toBe("GET");
    expect(fetch.mock.calls.filter((c) => callUrl(c).endsWith("/guion"))).toHaveLength(1);
    expect(descargar).toHaveBeenCalledWith("guion-oferta-LIC-1.pdf", expect.anything(), "guion");
  });

  it("un 404 explica que hay que volver a generarlo", async () => {
    const { toast } = await import("@/lib/toast");
    const aviso = vi.spyOn(toast, "error").mockImplementation(() => "id");
    fetchPorRuta(
      [/guion\.pdf$/, { detail: "No hay guion generado" }, 404],
      [/\/guion$/, GUION],
      [/documentos$/, DOCUMENTOS],
    );
    renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));
    fireEvent.click(await screen.findByRole("button", { name: "Descargar PDF" }));

    await vi.waitFor(() => expect(aviso).toHaveBeenCalled());
    expect(aviso.mock.calls[0][1]?.description).toMatch(/Vuelve a generarlo/);
    aviso.mockRestore();
  });
});

describe("guionAMarkdown", () => {
  it("es un esquema por criterio con referencias, no con el texto citado", () => {
    const md = guionAMarkdown(GUION, () => "PPT.pdf");
    expect(md).toContain("## Metodología (30 puntos)");
    expect(md).toContain("- Plan de migración por fases. _(PPT.pdf p. 4)_");
    expect(md).toContain("- Oficina de proyecto con PMO propia. _[sin base en el pliego]_");
    expect(md).not.toContain("migración»");
    expect(md).not.toContain("De tus documentos");
  });

  it("lleva las citas de documentos propios con su extracto, fichero y página", () => {
    const [criterio] = GUION.criterios!;
    const conPropias: GuionOferta = {
      ...GUION,
      criterios: [
        {
          ...criterio,
          citas_organizacion: [
            {
              attachment_id: 11,
              filename: "Propuesta.pdf",
              page_number: 3,
              cita: "Migramos el ERP en nueve meses.",
              pursuit_id: 42,
              licitacion_id: "EXP-1",
            },
            {
              attachment_id: 12,
              filename: "Notas.txt",
              page_number: null,
              cita: "Equipo de seis personas.",
              pursuit_id: 42,
              licitacion_id: "EXP-1",
            },
          ],
        },
      ],
    };
    const md = guionAMarkdown(conPropias, () => "PPT.pdf");
    expect(md).toContain("### De tus documentos");
    expect(md).toContain("- «Migramos el ERP en nueve meses.» _(Propuesta.pdf p. 3)_");
    expect(md).toContain("- «Equipo de seis personas.» _(Notas.txt)_");
  });
});

describe("GuionOfertaPanel · PDF de la organización activa", () => {
  it("pide el PDF con la misma organización que el guion", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 9 });
    try {
      const fetch = fetchPorRuta(
        [/guion\.pdf/, { ok: true }],
        [/\/guion\?/, GUION],
        [/documentos$/, DOCUMENTOS],
      );
      renderConQuery(<GuionOfertaPanel licitacionId="LIC-1" />);
      fireEvent.click(screen.getByRole("button", { name: "Generar guion" }));
      fireEvent.click(await screen.findByRole("button", { name: "Descargar PDF" }));

      await vi.waitFor(() =>
        expect(fetch.mock.calls.some((c) => callUrl(c).includes("/guion.pdf"))).toBe(true),
      );
      const pdf = fetch.mock.calls.find((c) => callUrl(c).includes("/guion.pdf"))!;
      expect(callUrl(pdf)).toMatch(/guion\.pdf\?organization_id=9$/);
    } finally {
      useOrganizationStore.setState({ activeOrganizationId: null });
    }
  });
});
