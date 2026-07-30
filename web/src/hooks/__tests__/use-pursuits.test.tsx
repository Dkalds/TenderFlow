import * as React from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useCreatePursuit, usePursuits } from "@/hooks/use-pursuits";
import { useOrganizationStore } from "@/hooks/use-organization";

const pursuit = {
  id: 1, organization_id: 1, licitacion_id: "lic-1", tender_title: "Servicio TI",
  tender_deadline: null, responsible_user_id: null, responsible_name: null, status: "identified", decision: "pending",
  decision_reason: null, offer_price_eur: null, outcome: "pending", awarded_amount_eur: null,
  outcome_reason: null, identified_at: "2026-07-30T10:00:00Z", decision_at: null, submitted_at: null, closed_at: null,
  created_at: "2026-07-30T10:00:00Z", updated_at: "2026-07-30T10:00:00Z", version: 1,
} as const;

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  useOrganizationStore.setState({ activeOrganizationId: null });
  vi.unstubAllGlobals();
});

describe("pursuit hooks", () => {
  it("loads a filtered opportunity list through the product contract", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.includes("/organizations")
              ? [{ id: 1, name: "Equipo", is_personal: true, role: "owner", created_at: "2026-07-30T10:00:00Z" }]
              : { items: [pursuit], total: 1 },
          ),
          { status: 200 },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePursuits({ status: "identified" }), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items[0].id).toBe(1);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("status=identified"))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("organization_id=1"))).toBe(true);
  });

  it("creates an opportunity with the selected tender id", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    const fetchMock = vi.fn().mockImplementation((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.includes("/organizations")
              ? [{ id: 1, name: "Equipo", is_personal: true, role: "owner", created_at: "2026-07-30T10:00:00Z" }]
              : pursuit,
          ),
          { status: 200 },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useCreatePursuit(), { wrapper });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/organizations"))).toBe(true),
    );

    await result.current.mutateAsync({ licitacion_id: "lic-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/pursuits",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ licitacion_id: "lic-1", organization_id: 1 }),
      }),
    );
  });
});
