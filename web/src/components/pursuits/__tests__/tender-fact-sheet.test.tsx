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
        technical_solvency: [], economic_solvency: [], guarantees: [], penalties: [], subcontracting: [], team_requirements: [], extensions: [], critical_deadlines: [],
      },
    },
  }),
  useExtractTenderFactSheet: () => ({ mutateAsync: extract, isPending: false }),
}));

import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";

describe("TenderFactSheetPanel", () => {
  it("renders facts with confidence and an auditable document/page citation", () => {
    render(<TenderFactSheetPanel licitacionId="LIC-1" />);
    expect(screen.getByText("Criterios de adjudicación")).toBeInTheDocument();
    expect(screen.getByText("Precio")).toBeInTheDocument();
    expect(screen.getByText("86% confianza")).toBeInTheDocument();
    expect(screen.getByText(/1 cita verificable/)).toBeInTheDocument();
  });
});
