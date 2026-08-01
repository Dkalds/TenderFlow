import * as React from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useRadar } from "@/hooks/use-radar";

const tender = (id: string, fecha_publicacion: string, tecnologia = "SAP") => ({
  id_externo: id,
  titulo: `Licitación ${id}`,
  organo_contratacion: "Ayuntamiento",
  importe: 120000,
  estado: "PUB",
  fecha_publicacion,
  fecha_limite: "2026-12-01T00:00:00Z",
  ccaa: "MAD",
  cpv: "72000000",
  url: null,
  tecnologia,
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Responde al listado y al scoring según la URL pedida. */
function stubApi(options: {
  items: ReturnType<typeof tender>[];
  opportunities?: Array<{ id_externo: string; score: number; band: string }>;
}) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    const body = String(url).includes("/analytics/scoring")
      ? { opportunities: options.opportunities ?? [] }
      : { items: options.items };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRadar", () => {
  it("asks for the newest tenders, not the oldest", async () => {
    // Regresión: `-fecha_publicacion` es ASCENDENTE en el backend, así que el
    // radar listaba las licitaciones más antiguas de la base.
    const fetchMock = stubApi({ items: [tender("NEW", "2026-07-01")] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const listingCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/v1/licitaciones"),
    );
    expect(listingCall).toBeDefined();
    expect(String(listingCall![0])).toContain("sort=fecha_publicacion");
    expect(String(listingCall![0])).not.toContain("sort=-fecha_publicacion");
  });

  it("merges the backend score and band onto the listing rows", async () => {
    stubApi({
      items: [tender("A", "2026-07-01"), tender("B", "2026-06-01")],
      opportunities: [{ id_externo: "A", score: 87, band: "Caliente" }],
    });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data?.items[0].band).toBe("Caliente"));

    const [first, second] = result.current.data!.items;
    expect(first.score).toBe(87);
    // Una licitación sin score no inventa uno: la página cae a su copy neutra.
    expect(second.score).toBeUndefined();
    expect(second.band).toBeUndefined();
  });

  it("orders by the backend score, not by publication date", async () => {
    // Regresión: la página prometía "señales priorizadas" y renderizaba en
    // orden cronológico — el score sólo decoraba la fila. La jerarquía visual
    // afirmaba un ranking que el dato no respaldaba (anti-patrón 1 de
    // docs/frontend-data-invariants.md, aplicado al orden en vez de al número).
    stubApi({
      items: [tender("RECIENTE", "2026-07-10"), tender("ANTIGUA", "2026-06-01")],
      opportunities: [
        { id_externo: "RECIENTE", score: 20, band: "Tibia" },
        { id_externo: "ANTIGUA", score: 91, band: "Caliente" },
      ],
    });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data?.items[0].score).toBe(91));

    expect(result.current.data!.items.map((item) => item.id_externo)).toEqual([
      "ANTIGUA",
      "RECIENTE",
    ]);
  });

  it("pushes unscored tenders to the end instead of ranking them first", async () => {
    stubApi({
      items: [tender("SIN_SCORE", "2026-07-10"), tender("CON_SCORE", "2026-06-01")],
      opportunities: [{ id_externo: "CON_SCORE", score: 40, band: "Tibia" }],
    });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data?.items[0].score).toBe(40));

    expect(result.current.data!.items.at(-1)!.id_externo).toBe("SIN_SCORE");
  });

  it("flags that the order is not final while scoring is in flight", async () => {
    stubApi({
      items: [tender("A", "2026-07-01")],
      opportunities: [{ id_externo: "A", score: 50, band: "Tibia" }],
    });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    await waitFor(() => expect(result.current.isRanking).toBe(false));
  });

  it("carries the deadline the card renders", async () => {
    stubApi({ items: [tender("A", "2026-07-01")] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.data!.items[0].fecha_limite).toBe("2026-12-01T00:00:00Z");
  });

  it("does not ask for scoring when the listing is empty", async () => {
    const fetchMock = stubApi({ items: [] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.data!.items).toEqual([]);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/analytics/scoring"))).toBe(
      false,
    );
  });

  it("surfaces a listing failure as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.error).toBeTruthy());

    expect(result.current.data).toBeUndefined();
  });

  it("omits the tecnologia param when null (no filter applied)", async () => {
    const fetchMock = stubApi({ items: [] });

    const { result } = renderHook(() => useRadar(null), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const listingCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/v1/licitaciones"),
    );
    expect(String(listingCall![0])).not.toContain("tecnologia=");
  });

  it("includes the tecnologia param when a single value is selected", async () => {
    const fetchMock = stubApi({ items: [] });

    const { result } = renderHook(() => useRadar("IA"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const listingCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/v1/licitaciones"),
    );
    expect(String(listingCall![0])).toContain("tecnologia=IA");
  });

  it("uses a distinct query key per tecnologia so switching the filter refetches", async () => {
    const fetchMock = stubApi({ items: [] });

    const { rerender } = renderHook(
      ({ tecnologia }: { tecnologia: string | null }) => useRadar(tecnologia),
      { wrapper, initialProps: { tecnologia: null as string | null } },
    );
    rerender({ tecnologia: "Cloud" });

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/v1/licitaciones"))
          .length,
      ).toBeGreaterThanOrEqual(2),
    );
  });
});
