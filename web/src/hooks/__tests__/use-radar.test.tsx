import * as React from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  useDismissRadarTender,
  useRadar,
  useRadarDismissals,
  useRestoreRadarTender,
} from "@/hooks/use-radar";

/**
 * El Radar consume `GET /analytics/scoring?limit=24` como fuente única: es el
 * top-24 por potencial comercial de todo el corpus abierto. Antes pedía el
 * listado por fecha y le alineaba el score por id, así que mostraba "las 24
 * abiertas más recientes reordenadas" mientras la UI prometía priorización de
 * mercado — el orden era lo fabricado, no el número.
 */
const scored = (id: string, score: number, tecnologia = "SAP") => ({
  id_externo: id,
  titulo: `Licitación ${id}`,
  organo_contratacion: "Ayuntamiento",
  importe: 120000,
  fecha_limite: "2026-12-01T00:00:00Z",
  fecha_publicacion: "2026-07-01T00:00:00Z",
  ccaa: "MAD",
  cpv: "72000000",
  tecnologia,
  ml_tech_principal: null,
  score,
  band: score >= 75 ? "Caliente" : "Tibia",
  risk_flags: [],
  desglose: {},
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function stubApi(options: {
  opportunities?: ReturnType<typeof scored>[];
  dismissals?: string[];
}) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    const target = String(url);
    const body = target.includes("/radar/dismissals")
      ? { ids: options.dismissals ?? [] }
      : { opportunities: options.opportunities ?? [] };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRadar", () => {
  it("consume el ranking de mercado, no el listado por fecha", async () => {
    const fetchMock = stubApi({ opportunities: [scored("A", 87)] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const calls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(calls.some((url) => url.includes("/api/v1/analytics/scoring"))).toBe(true);
    expect(calls.some((url) => url.includes("/api/v1/licitaciones"))).toBe(false);
  });

  it("pide exactamente las 24 filas que la página promete", async () => {
    const fetchMock = stubApi({ opportunities: [scored("A", 50)] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const scoringCall = fetchMock.mock.calls
      .map(([url]) => String(url))
      .find((url) => url.includes("/analytics/scoring"));
    expect(scoringCall).toContain("limit=24");
  });

  it("pide el ranking sin las señales que el usuario descartó", async () => {
    // Excluirlas en cliente sobre el top-24 ya cortado dejaba la bandeja vacía
    // a quien triaba las 24: las descartadas seguían ocupando su plaza en el
    // corte y no entraba nada detrás. El backend las quita antes de ordenar.
    const fetchMock = stubApi({ opportunities: [scored("A", 50)] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const scoringCall = fetchMock.mock.calls
      .map(([url]) => String(url))
      .find((url) => url.includes("/analytics/scoring"));
    expect(scoringCall).toContain("exclude_dismissed=true");
  });

  it("respeta el orden que devuelve el backend sin reordenar en cliente", async () => {
    // La puntuación y el orden se calculan en servidor (ADR-014): aquí no se
    // deriva ninguna dimensión.
    stubApi({ opportunities: [scored("PRIMERA", 91), scored("SEGUNDA", 20)] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.data!.items.map((item) => item.id_externo)).toEqual([
      "PRIMERA",
      "SEGUNDA",
    ]);
  });

  it("trae el plazo y la tecnología que la tarjeta pinta", async () => {
    // Sin estos dos campos en `ScoredOpportunity` el Radar no podía usar este
    // endpoint como fuente: era el bloqueo que dejaba la lista a medias.
    stubApi({ opportunities: [scored("A", 60, "Salesforce")] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.data!.items[0].fecha_limite).toBe("2026-12-01T00:00:00Z");
    expect(result.current.data!.items[0].tecnologia).toBe("Salesforce");
  });

  it("manda la tecnología al backend en vez de filtrar el top-24 recibido", async () => {
    // Filtrando en cliente, el top-24 se calcula sobre el corpus entero y luego
    // se recorta: con 13 licitaciones SAP vivas entre 1.643, la bandeja de SAP
    // salía vacía aunque esas 13 existieran. El filtro tiene que acotar el
    // universo antes de ordenar y cortar (ADR-014, invariante 1).
    const fetchMock = stubApi({ opportunities: [scored("SF", 70, "Salesforce")] });

    const { result } = renderHook(() => useRadar("Salesforce"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const scoringCall = fetchMock.mock.calls
      .map(([url]) => String(url))
      .find((url) => url.includes("/analytics/scoring"));
    expect(scoringCall).toContain("tecnologia=Salesforce");
    expect(result.current.data!.items.map((item) => item.id_externo)).toEqual(["SF"]);
  });

  it("sin tecnología seleccionada no manda el parámetro", async () => {
    const fetchMock = stubApi({ opportunities: [scored("A", 50)] });

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const scoringCall = fetchMock.mock.calls
      .map(([url]) => String(url))
      .find((url) => url.includes("/analytics/scoring"));
    expect(scoringCall).not.toContain("tecnologia=");
  });
});

describe("descarte server-side", () => {
  it("lee los descartes persistidos del usuario", async () => {
    // Antes vivían en `React.useState`: el usuario triaba 24 señales,
    // recargaba y volvían las 24.
    stubApi({ dismissals: ["YA-DESCARTADA"] });

    const { result } = renderHook(() => useRadarDismissals(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(["YA-DESCARTADA"]));
  });

  it("descartar hace POST y refleja la señal al momento", async () => {
    const fetchMock = stubApi({ dismissals: [] });

    const { result } = renderHook(
      () => ({ list: useRadarDismissals(), dismiss: useDismissRadarTender() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.list.data).toEqual([]));

    await act(async () => {
      await result.current.dismiss.mutateAsync("NUEVA");
    });

    const posted = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes("/radar/dismissals") &&
        (init as RequestInit | undefined)?.method === "POST",
    );
    expect(posted).toBeDefined();
  });

  it("deshacer hace DELETE sobre el id descartado", async () => {
    const fetchMock = stubApi({ dismissals: ["DESCARTADA"] });

    const { result } = renderHook(() => useRestoreRadarTender(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("DESCARTADA");
    });

    const deleted = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deleted).toBeDefined();
    expect(String(deleted![0])).toContain("DESCARTADA");
  });
});
