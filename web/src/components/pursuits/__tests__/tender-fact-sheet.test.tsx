import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const extract = vi.fn();
vi.mock("@/hooks/use-tender-fact-sheet", () => ({
  useTenderFactSheet: () => ({
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
  useExtractTenderFactSheet: () => ({ mutateAsync: extract, isPending: false }),
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
