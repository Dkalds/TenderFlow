/**
 * Tests for src/hooks/use-ask.ts (useChat + useAskModels).
 *
 * Strategy:
 *  - Mock `@/lib/ask-stream` so streamAsk is a vi.fn() we fully control.
 *  - useAskModels uses fetch via react-query; mock fetch globally for those.
 *  - Each renderHook gets a fresh QueryClient (retry: false) to avoid state bleed.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { AskParams, AskStreamResult } from "@/lib/ask-stream";

// ── Mock ask-stream before importing the hook ──────────────────────────────────
const mockStreamAsk = vi.fn<(params: AskParams) => Promise<AskStreamResult>>();

vi.mock("@/lib/ask-stream", () => ({
  streamAsk: (...args: Parameters<typeof mockStreamAsk>) => mockStreamAsk(...args),
}));

// ── Subject under test ─────────────────────────────────────────────────────────
import { useChat, useAskModels } from "@/hooks/use-ask";

// ── Helpers ────────────────────────────────────────────────────────────────────

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

function makeResult(overrides: Partial<AskStreamResult> = {}): AskStreamResult {
  return { answer: "", fuentes: [], degraded: null, resumenMeta: null, ...overrides };
}

/** Build a minimal Response-like object. */
function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    headers: { get: () => "application/json" },
  } as unknown as Response;
}

// ── Setup / teardown ───────────────────────────────────────────────────────────

beforeEach(() => {
  mockStreamAsk.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── useChat tests ──────────────────────────────────────────────────────────────

describe("useChat", () => {
  it("returns the initial idle state", () => {
    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    expect(result.current.messages).toEqual([]);
    expect(result.current.streaming).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(typeof result.current.send).toBe("function");
    expect(typeof result.current.stop).toBe("function");
    expect(typeof result.current.reset).toBe("function");
  });

  it("ignores empty / whitespace-only questions", async () => {
    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("   ");
    });

    expect(mockStreamAsk).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("appends user + assistant turns and streams tokens into the last turn", async () => {
    let resolveStream!: (v: AskStreamResult) => void;
    mockStreamAsk.mockImplementation(({ onToken }) => {
      return new Promise<AskStreamResult>((resolve) => {
        onToken("Hola ");
        resolveStream = (r) => {
          onToken(r.answer);
          resolve(r);
        };
      });
    });

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    act(() => {
      void result.current.send("Saluda");
    });

    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.streaming).toBe(true);
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toEqual({ role: "user", content: "Saluda" });
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].content).toBe("Hola ");

    await act(async () => {
      resolveStream(makeResult({ answer: "Hola mundo" }));
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.messages[1].content).toBe("Hola mundo");
    expect(result.current.streaming).toBe(false);
  });

  it("sends the previous turns as messages history on the next send", async () => {
    mockStreamAsk.mockImplementation(async ({ onToken }) => {
      onToken("Respuesta 1");
      return makeResult({ answer: "Respuesta 1" });
    });

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("Primera pregunta");
    });
    await act(async () => {
      await result.current.send("¿Y el plazo?");
    });

    expect(mockStreamAsk).toHaveBeenCalledTimes(2);
    const secondCall = mockStreamAsk.mock.calls[1][0];
    expect(secondCall.question).toBe("¿Y el plazo?");
    expect(secondCall.messages).toEqual([
      { role: "user", content: "Primera pregunta" },
      { role: "assistant", content: "Respuesta 1" },
    ]);
  });

  it("passes idExterno, model and topK to streamAsk", async () => {
    mockStreamAsk.mockResolvedValue(makeResult({ answer: "ok" }));

    const { result } = renderHook(() => useChat({ idExterno: "EXP-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.send("pregunta", { model: "gpt-4o", topK: 5 });
    });

    expect(mockStreamAsk).toHaveBeenCalledWith(
      expect.objectContaining({
        question: "pregunta",
        idExterno: "EXP-1",
        model: "gpt-4o",
        topK: 5,
      }),
    );
  });

  it("attaches fuentes and degraded metadata to the assistant turn", async () => {
    const fuentes = [{ id_externo: "EXP-1", titulo: "T", chunks: [{ chunk_index: 0, texto: "frag" }] }];
    mockStreamAsk.mockResolvedValue(makeResult({ answer: "respuesta", fuentes, degraded: null }));

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("pregunta");
    });

    const last = result.current.messages[1];
    expect(last.content).toBe("respuesta");
    expect(last.fuentes).toEqual(fuentes);
  });

  it("sets error and drops the empty assistant placeholder on failure", async () => {
    mockStreamAsk.mockRejectedValue(new Error("Error 503"));

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("¿Falla el servidor?");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("Error 503");
    // El turno user queda; el placeholder assistant vacío se elimina.
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("user");
  });

  it("uses 'Error desconocido' for non-Error throws", async () => {
    mockStreamAsk.mockRejectedValue("string error");

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("¿Algo raro?");
    });

    await waitFor(() => expect(result.current.error).toBe("Error desconocido"));
  });

  it("silently swallows AbortError (request cancelled)", async () => {
    const abortError = new DOMException("The user aborted a request.", "AbortError");
    mockStreamAsk.mockRejectedValue(abortError);

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("Pregunta cancelada");
    });

    expect(result.current.error).toBeNull();
  });

  it("reset() clears the conversation and error state", async () => {
    mockStreamAsk.mockRejectedValue(new Error("fallo"));

    const { result } = renderHook(() => useChat(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.send("pregunta");
    });
    await waitFor(() => expect(result.current.error).toBe("fallo"));

    act(() => {
      result.current.reset();
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.streaming).toBe(false);
    expect(result.current.loading).toBe(false);
  });
});

// ── useAskModels tests ─────────────────────────────────────────────────────────

describe("useAskModels", () => {
  it("returns the models array from a successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(["gpt-4", "gpt-3.5"])));

    const { result } = renderHook(() => useAskModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(["gpt-4", "gpt-3.5"]);
  });

  it("extracts models from a { models: [...] } shape", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ models: ["llama3"] })));

    const { result } = renderHook(() => useAskModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(["llama3"]);
  });

  it("returns [] on non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(null, 500)));

    const { result } = renderHook(() => useAskModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
