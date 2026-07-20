import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMutate = vi.fn().mockResolvedValue({});
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
  apiMutate: (...a: unknown[]) => apiMutate(...a),
}));
vi.mock("@/lib/report-error", () => ({ reportError: vi.fn() }));

import { AlertsFeed } from "@/app/(dashboard)/pipeline-alertas/_components/alerts-feed";

function renderFeed(data?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (data !== undefined) qc.setQueryData(["notifications"], data);
  return { qc, ...render(
    <QueryClientProvider client={qc}>
      <AlertsFeed />
    </QueryClientProvider>,
  ) };
}

afterEach(() => {
  apiMutate.mockClear();
});

describe("AlertsFeed", () => {
  it("shows an empty-state invite when there are no alerts", () => {
    renderFeed({ items: [], unread_count: 0, alerts: [], alerts_unread_count: 0, hoy: {} });
    expect(screen.getByText(/Sin alertas todavía/)).toBeInTheDocument();
  });

  it("renders alerts with an unread dot and no 'marcar leídas' button when all read", () => {
    renderFeed({
      items: [],
      unread_count: 0,
      alerts: [
        { id: 1, created_at: "2026-07-01T00:00:00Z", type: "rule_match", title: "SAP en Madrid", body: null, licitacion_id: "L1", rule_id: 5, read: true },
      ],
      alerts_unread_count: 0,
      hoy: {},
    });
    expect(screen.getByText("SAP en Madrid")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Marcar leídas/ })).not.toBeInTheDocument();
  });

  it("marks unread alerts as read and invalidates the shared notifications query", async () => {
    renderFeed({
      items: [],
      unread_count: 0,
      alerts: [
        { id: 1, created_at: "2026-07-01T00:00:00Z", type: "rule_match", title: "SAP en Madrid", body: null, licitacion_id: "L1", rule_id: 5, read: false },
        { id: 2, created_at: "2026-07-02T00:00:00Z", type: "rule_match", title: "Salesforce Cataluña", body: null, licitacion_id: "L2", rule_id: 6, read: false },
      ],
      alerts_unread_count: 2,
      hoy: {},
    });

    fireEvent.click(screen.getByRole("button", { name: /Marcar leídas \(2\)/ }));

    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/notifications/alerts/read", {
        ids: [1, 2],
      }),
    );
  });

  it("links alerts with a licitacion_id to the detail page", () => {
    renderFeed({
      items: [],
      unread_count: 0,
      alerts: [
        { id: 1, created_at: null, type: "rule_match", title: "Con licitación", body: null, licitacion_id: "L1", rule_id: null, read: false },
        { id: 2, created_at: null, type: "deadline_7", title: "Sin licitación", body: null, licitacion_id: null, rule_id: null, read: false },
      ],
      alerts_unread_count: 2,
      hoy: {},
    });
    const link = screen.getByText("Con licitación").closest("a");
    expect(link).toHaveAttribute("href", "/detalle?lic=L1");
    expect(screen.getByText("Sin licitación").closest("a")).toBeNull();
  });
});
