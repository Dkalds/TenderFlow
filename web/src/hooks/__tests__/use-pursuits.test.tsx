import * as React from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import {
  pursuitKeys,
  useCreatePursuit,
  usePipelineAgenda,
  usePursuits,
  useUpdatePursuit,
} from "@/hooks/use-pursuits";
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

    expect(result.current.data?.items?.[0].id).toBe(1);
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

  it("seeds the detail cache under the key the detail view reads", async () => {
    // `usePursuit` lee `[...detail(id), organizationId]`. Sembrar sin la
    // organización dejaba el dato en una entrada huérfana y el detalle sólo se
    // actualizaba cuando volvía el refetch de la invalidación.
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    const updated = { ...pursuit, status: "qualifying", version: 2 };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(url).includes("/organizations")
                ? [{ id: 1, name: "Equipo", is_personal: true, role: "owner", created_at: "2026-07-30T10:00:00Z" }]
                : updated,
            ),
            { status: 200 },
          ),
        ),
      ),
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const localWrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useUpdatePursuit(1), { wrapper: localWrapper });
    await waitFor(() => expect(useOrganizationStore.getState().activeOrganizationId).toBe(1));
    await result.current.mutateAsync({ status: "qualifying" });

    expect(client.getQueryData([...pursuitKeys.detail("1"), 1])).toMatchObject({ version: 2 });
  });
});

// `usePipelineAgenda` llegó sin un solo test que lo ejecutara: su único
// consumidor (AgendaView) mockea el módulo entero, así que las 10 ramas de su
// queryFn quedaron a 0 y tiraron el piso de cobertura de `src/hooks/**` por
// debajo del 66% que exige web/vitest.config.ts. Estos tests las ejercitan y,
// de paso, fijan el contrato que el hook implementa.

const agenda = {
  items: [],
  kpis: {},
  organization_id: 1,
  pursuits_total: 0,
  pursuits_truncados: false,
  renovaciones_horizonte_meses: 6,
  senales_truncadas: false,
  solo_mios: false,
} as const;

const ORG = {
  id: 1, name: "Equipo", is_personal: true, role: "owner", created_at: "2026-07-30T10:00:00Z",
} as const;

function stubApi(organizations: unknown[]) {
  const fetchMock = vi.fn().mockImplementation((url: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(String(url).includes("/organizations") ? organizations : agenda),
        { status: 200 },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function agendaUrls(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls
    .map((call) => String(call[0]))
    .filter((u) => u.includes("/pursuits/agenda"));
}

describe("usePipelineAgenda", () => {
  it("sin organización ni filtros pide la agenda sin query string", async () => {
    // Rama falsa de los cuatro condicionales y del ternario `query ? ... : ""`.
    const fetchMock = stubApi([]);

    const { result } = renderHook(
      () => usePipelineAgenda({ soloMios: false, tecnologia: null, ccaa: null }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const urls = agendaUrls(fetchMock);
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u === "/api/v1/pursuits/agenda")).toBe(true);
  });

  it("traslada los cuatro filtros al backend en vez de recortar en cliente", async () => {
    // Rama verdadera de los cuatro. Además fija ADR-014: el recorte por
    // tecnología/CCAA/solo_mios lo hace el backend sobre el dataset completo.
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    const fetchMock = stubApi([ORG]);

    const { result } = renderHook(
      () => usePipelineAgenda({ soloMios: true, tecnologia: "SAP", ccaa: "MAD" }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = agendaUrls(fetchMock).find((u) => u.includes("?"));
    expect(url).toContain("organization_id=1");
    expect(url).toContain("solo_mios=true");
    expect(url).toContain("tecnologia=SAP");
    expect(url).toContain("ccaa=MAD");
  });

  it("una mutación de pursuit invalida también la agenda", async () => {
    // La invalidación de la agenda descansa en que `["pursuits"]` es prefijo de
    // `pursuitKeys.agenda`. Es cierto hoy y nada lo sujetaba: si alguien cambia
    // esa clave, la agenda se queda rancia tras editar y ningún test se entera.
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    stubApi([ORG]);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const filters = { soloMios: false, tecnologia: null, ccaa: null };
    const agendaKey = [...pursuitKeys.agenda, filters, 1];
    client.setQueryData(agendaKey, agenda);
    const localWrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useUpdatePursuit(1), { wrapper: localWrapper });
    await waitFor(() => expect(useOrganizationStore.getState().activeOrganizationId).toBe(1));
    await result.current.mutateAsync({ status: "qualifying" });

    expect(client.getQueryState(agendaKey)?.isInvalidated).toBe(true);
  });
});
