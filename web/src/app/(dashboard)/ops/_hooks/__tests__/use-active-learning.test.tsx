/**
 * Las acciones de la cola por desacuerdo (plan de clasificación en tres
 * niveles, F1), vistas desde lo que llega a `POST /api/v1/feedback`: aceptar
 * la propuesta del LLM de un clic y marcar «es TI» sin familia.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import type { QueueItem } from "../../_lib/active-learning";
import { useActiveLearning } from "../use-active-learning";

const COLA: QueueItem[] = [
  {
    id_externo: "EXP-SI",
    motivo: "familias_distintas",
    llm: { es_ti: true, confianza_es_ti: 0.9, familias: ["DESARROLLO", "SAP"] },
  },
  {
    id_externo: "EXP-NO",
    motivo: "llm_no_reglas_si",
    llm: { es_ti: false, confianza_es_ti: 0.8, familias: [] },
  },
  {
    id_externo: "EXP-SIN-RESPUESTA",
    motivo: "familias_distintas",
    llm: { es_ti: null, confianza_es_ti: null, familias: ["ORACLE"] },
  },
];

function montar() {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/feedback/queue")) return Promise.resolve(jsonResponse({ items: COLA }));
    if (url === "/api/v1/feedback/model-info") {
      return Promise.resolve(jsonResponse({ active: null, feedbacks_since_train: 0, history: [] }));
    }
    if (url === "/api/v1/feedback" && callMethod(call) === "POST") {
      return Promise.resolve(jsonResponse({ status: "ok", expediente: "x", stored_at: "t" }, 201));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useActiveLearning(), { wrapper });
  return { fetchMock, hook };
}

/** Cuerpos JSON de los `POST /api/v1/feedback` enviados hasta ahora. */
function envios(fetchMock: ReturnType<typeof vi.fn>): unknown[] {
  return fetchMock.mock.calls
    .filter((call) => callUrl(call) === "/api/v1/feedback" && callMethod(call) === "POST")
    .map((call) => JSON.parse(String((call[1] as RequestInit).body)));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useActiveLearning — cola por desacuerdo", () => {
  it("empieza por la estrategia de desacuerdo", async () => {
    const { fetchMock, hook } = montar();

    await waitFor(() => expect(hook.result.current.items).toHaveLength(3));

    expect(hook.result.current.strategy).toBe("desacuerdo");
    expect(fetchMock.mock.calls.map((call) => callUrl(call))).toContain(
      "/api/v1/feedback/queue?strategy=desacuerdo&limit=20",
    );
  });

  it("aceptar la propuesta manda es_ti y las familias: la primera, principal", async () => {
    const { fetchMock, hook } = montar();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(3));

    act(() => hook.result.current.acceptLlmProposal("EXP-SI"));

    await waitFor(() => expect(envios(fetchMock)).toHaveLength(1));
    expect(envios(fetchMock)[0]).toEqual({
      expediente: "EXP-SI",
      relevante: true,
      tecnologia: "DESARROLLO",
      tecnologias_secundarias: ["SAP"],
    });
  });

  it("aceptar un «no es TI» manda relevante=false sin familias", async () => {
    const { fetchMock, hook } = montar();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(3));

    act(() => hook.result.current.acceptLlmProposal("EXP-NO"));

    await waitFor(() => expect(envios(fetchMock)).toHaveLength(1));
    expect(envios(fetchMock)[0]).toEqual({ expediente: "EXP-NO", relevante: false });
  });

  it("sin respuesta del LLM sobre si es TI, aceptar no envía nada", async () => {
    const { fetchMock, hook } = montar();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(3));

    act(() => hook.result.current.acceptLlmProposal("EXP-SIN-RESPUESTA"));
    // Testigo: una acción que sí envía. El envío es asíncrono, así que mirar
    // justo después del clic no prueba nada; cuando llega el POST del testigo,
    // el de la aceptación ya habría llegado antes.
    act(() => hook.result.current.markTiWithoutFamily("EXP-NO"));

    await waitFor(() => expect(envios(fetchMock)).toHaveLength(1));
    expect(envios(fetchMock)).toEqual([{ expediente: "EXP-NO", relevante: true }]);
  });

  it("«es TI, sin familia» manda relevante=true sin tecnologías", async () => {
    const { fetchMock, hook } = montar();
    await waitFor(() => expect(hook.result.current.items).toHaveLength(3));

    act(() => hook.result.current.markTiWithoutFamily("EXP-SIN-RESPUESTA"));

    await waitFor(() => expect(envios(fetchMock)).toHaveLength(1));
    expect(envios(fetchMock)[0]).toEqual({ expediente: "EXP-SIN-RESPUESTA", relevante: true });
  });
});
