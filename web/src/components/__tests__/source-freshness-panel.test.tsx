import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/hooks/use-source-freshness", () => ({
  useSourceFreshness: () => ({
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
    data: {
      healthy_sources: 1, total_sources: 2, healthy_sources_pct: 50, generated_at: "2026-07-30T00:00:00Z",
      sources: [
        { source: "PLACSP", status: "success", last_success_at: "2026-07-30T09:00:00Z", last_seen_updated: null, cursor_updated_at: null, lag_hours: 2, detected_within_24h_pct: 97.5, sample_size: 40, fetched: 10, parsed: 10, discarded: 0, errors: 0, is_degraded: false, warning: null },
        { source: "TED", status: "failed", last_success_at: null, last_seen_updated: null, cursor_updated_at: null, lag_hours: null, detected_within_24h_pct: null, sample_size: 0, fetched: 0, parsed: 0, discarded: 0, errors: 1, is_degraded: true, warning: "No hay una ingesta exitosa registrada." },
      ],
    },
  }),
}));

import { SourceFreshnessPanel } from "@/components/source-freshness-panel";

describe("SourceFreshnessPanel", () => {
  it("makes a degraded source visible alongside its SLA measurements", () => {
    render(<SourceFreshnessPanel />);
    expect(screen.getByText(/1 fuente degradada/)).toBeInTheDocument();
    expect(screen.getByText("PLACSP")).toBeInTheDocument();
    expect(screen.getByText("TED")).toBeInTheDocument();
    expect(screen.getByText("97,5%")).toBeInTheDocument();
    expect(screen.getByText("Sin ingesta")).toBeInTheDocument();
  });
});
