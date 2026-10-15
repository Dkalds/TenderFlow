import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const extract = vi.fn();
// v148: lo que devuelve cada fuente se cambia por test. Por defecto, la ficha
// del pliego y ninguna condición oficial: el caso de antes de v148.
const h = vi.hoisted(() => ({ sinFicha: false, oficiales: undefined as unknown }));
vi.mock("@/hooks/use-condiciones-oficiales", () => ({
  useCondicionesOficiales: () => ({ isLoading: false, error: null, data: h.oficiales }),
}));
vi.mock("@/hooks/use-tender-fact-sheet", () => ({
  useTenderFactSheet: () => h.sinFicha ? { isLoading: false, error: null, refetch: vi.fn(), data: undefined } : ({
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    data: {
      licitacion_id: "LIC-1", status: "extracted", extraction_version: "facts-v1", model: "test",
      field_count: 1, evidence_count: 1, error_detail: null, extracted_at: null, updated_at: "2026-07-30T00:00:00Z",
      facts: {
        award_criteria: [{ name: "Precio", description: "Oferta económica", confidence: 0.86, weight_pct: 55, evidence: [{ documento_id: 7, page_number: 3, quote: "El precio tiene un peso del 55%.", start_offset: 0, end_offset: 30 }] }],
        lots: [{ lot_number: "1", name: "Implantación SAP", description: "Lote 1: implantación del ERP", amount_eur: 1200000, confidence: 0.9, evidence: [{ documento_id: 7, page_number: 2, quote: "Lote 1: implantación", start_offset: 0, end_offset: 20 }] }],
        service_levels: [{ name: "Disponibilidad del servicio", target: "99,9% mensual", description: "ANS de disponibilidad", confidence: 0.8, evidence: [{ documento_id: 7, page_number: 9, quote: "disponibilidad del 99,9%", start_offset: 0, end_offset: 24 }] }],
        certifications: [{ name: "ISO 27001", scope: "company", description: "Certificación de seguridad exigida", confidence: 0.85, evidence: [{ documento_id: 7, page_number: 5, quote: "certificado ISO 27001", start_offset: 0, end_offset: 21 }] }],
        technical_solvency: [], economic_solvency: [], guarantees: [], penalties: [], subcontracting: [], team_requirements: [], extensions: [], critical_deadlines: [],
      },
    },
  }),
  useTenderFactSheetExtraction: () => ({ start: extract, isStarting: false, running: false }),
  useFactSheetDocumentos: () => ({
    data: {
      id_externo: "LIC-1",
      items: [
        {
          id: 7,
          tipo: "legal",
          uri: "https://placsp.example/pcap.pdf",
          filename: "PCAP.pdf",
          content_type: "application/pdf",
          size_bytes: 1000,
          status: "extracted",
          created_at: "2026-07-30T00:00:00Z",
        },
      ],
    },
  }),
}));

// El visor de página (F2.5) pide su texto con React Query; aquí basta con
// comprobar que la cita llega al visor con su documento, página y offsets.
const paginaPedida = vi.fn();
vi.mock("@/hooks/use-pagina-documento", () => ({
  usePaginaDocumento: (_id: string, solicitud: unknown) => {
    paginaPedida(solicitud);
    return {
      isLoading: false,
      error: null,
      data: {
        documento_id: 7,
        page_number: 3,
        texto: "Cláusula 9. El precio tiene un peso del 55%. Resto.",
        total_paginas: 20,
        resaltado_inicio: 12,
        resaltado_fin: 44,
        filename: "PCAP.pdf",
      },
    };
  },
}));

import { fireEvent } from "@testing-library/react";
import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";

describe("TenderFactSheetPanel", () => {
  it("renders facts with ordinal confidence and an auditable document/page citation", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);
    expect(screen.getByText("Criterios de adjudicación")).toBeInTheDocument();
    expect(screen.getByText("Precio")).toBeInTheDocument();
    // La confianza autoinformada del LLM se presenta como ordinal, con el
    // número crudo como detalle — no como un porcentaje que aparente calibración.
    expect(screen.getByText(/Confianza alta · 86%/)).toBeInTheDocument();
    expect(screen.getAllByText(/1 cita verificable/).length).toBeGreaterThan(0);
  });

  it("resolves citations to the document filename with a page deeplink", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);
    const enlaces = screen.getAllByRole("link", { name: /PCAP\.pdf · página/ });
    expect(enlaces.length).toBeGreaterThan(0);
    expect(enlaces[0]).toHaveAttribute("href", expect.stringContaining("#page="));
  });

  it("F2.5: una cita abre su página con el fragmento resaltado", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);
    // La primera cita pintada es la del criterio «Precio» (página 3).
    fireEvent.click(screen.getAllByRole("button", { name: "Ver la cita en su página" })[1]);

    expect(paginaPedida).toHaveBeenLastCalledWith({ documentoId: 7, pagina: 3, inicio: 0, fin: 30 });
    const visor = screen.getByRole("dialog");
    expect(visor).toHaveTextContent("PCAP.pdf · página 3 de 20");
    expect(visor.querySelector("mark")).toHaveTextContent("El precio tiene un peso del 55%.");
  });

  it("no avisa de procedencia cuando la ficha es de la propia licitación", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);
    expect(screen.queryByText(/expediente original/)).not.toBeInTheDocument();
  });

  it("dice de qué expediente salen los pliegos cuando es una republicación", () => {
    // La API sirve la ficha de la canónica (`licitacion_id` "LIC-1") a quien
    // la pide desde el anuncio TED.
    render(<TenderFactSheetPanel licitacionId="ted:657574-2026" />);
    expect(screen.getByRole("note")).toHaveTextContent("Pliegos del expediente original LIC-1");
  });

  it("renders v3 families: lots with number, SLAs with target and certifications with scope", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);
    expect(screen.getByText("Lotes")).toBeInTheDocument();
    expect(screen.getByText("Implantación SAP")).toBeInTheDocument();
    expect(screen.getByText("Lote 1")).toBeInTheDocument();
    expect(screen.getByText("Niveles de servicio (ANS/SLA)")).toBeInTheDocument();
    expect(screen.getByText("Objetivo 99,9% mensual")).toBeInTheDocument();
    expect(screen.getByText("Certificaciones")).toBeInTheDocument();
    expect(screen.getByText("ISO 27001")).toBeInTheDocument();
    expect(screen.getByText("Empresa")).toBeInTheDocument();
  });
});

describe("TenderFactSheetPanel — publicación oficial como fuente primaria (v148)", () => {
  const OFICIALES = {
    licitacion_id: "LIC-1",
    fuente: "placsp",
    url_publicacion: "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=1",
    actualizado: "2026-10-12T10:00:00Z",
    ambitos: [
      {
        lote_numero: null,
        lote_titulo: null,
        criterios: [
          { orden: 1, padre_orden: null, descripcion: "Oferta económica oficial", peso: 60, peso_pct: 60, es_precio: true, tipo_codigo: null, subtipo_codigo: null, nota: null },
        ],
        garantias: [],
        solvencia: [],
      },
    ],
  };

  afterEach(() => {
    h.sinFicha = false;
    h.oficiales = undefined;
  });

  it("enseña primero la publicación oficial y después lo extraído del pliego, separados", () => {
    h.oficiales = OFICIALES;
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);

    const oficial = screen.getByText("Publicación oficial (PLACSP)");
    const pliego = screen.getByText("Extraído del pliego");
    expect(screen.getByText("Oferta económica oficial")).toBeInTheDocument();
    // El criterio del LLM sigue ahí, en su sección y con su cita.
    expect(screen.getByText("Oferta económica")).toBeInTheDocument();
    expect(oficial.compareDocumentPosition(pliego) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sin ficha del pliego, la publicación oficial se ve igual y la extracción se ofrece aparte", () => {
    h.oficiales = OFICIALES;
    h.sinFicha = true;
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);

    expect(screen.getByText("Oferta económica oficial")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extraer ficha" })).toBeInTheDocument();
  });

  it("sin condiciones oficiales no añade ni la sección ni el rótulo de procedencia", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);

    expect(screen.queryByText("Publicación oficial (PLACSP)")).not.toBeInTheDocument();
    expect(screen.queryByText("Extraído del pliego")).not.toBeInTheDocument();
  });
});
