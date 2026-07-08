/**
 * Tests for src/hooks/use-ask.ts
 *
 * Strategy:
 *  - Mock `@/lib/ask-stream` so streamAsk is a vi.fn() we fully control.
 *  - useAsk also exports useAskModels (uses fetch via react-query); mock fetch
 *    globally for those tests.
 *  - Each renderHook gets a fresh QueryClient (retry: false) to avoid state bleed.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ── Mock ask-stream before importing the hook ──────────────────────────────────
const mockStreamAsk = vi.fn<
  (params: import("@/lib/ask-stream").AskParams) => Promise<string>
>();

vi.mock("@/lib/ask-stream", () => ({
  streamAsk: (...args: Parameters<typeof mockStreamAsk>) =>
    mockStreamAsk(...args),
}));

// ── Subject under test ─────────────────────────────────────────────────────────
import { useAsk, useAskModels } from "@/hooks/use-ask";

// ── Helpers ────────────────────────────────────────────────────────────────────

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
  };
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

// ── useAsk tests ───────────────────────────────────────────────────────────────

describe("useAsk", () => {
  it("returns the initial idle state", () => {
    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    expect(result.current.answer).toBeNull();
    expect(result.current.streaming).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(typeof result.current.ask).toBe("function");
    expect(typeof result.current.reset).toBe("function");
  });

  it("ignores empty / whitespace-only questions", async () => {
    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("   ");
    });

    expect(mockStreamAsk).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
  });

  it("sets loading=true and streaming=true while streamAsk is pending, then resolves", async () => {
    // Never-resolving promise to capture in-flight state.
    let resolveStream!: (v: string) => void;
    mockStreamAsk.mockImplementation(({ onToken }) => {
      return new Promise<string>((resolve) => {
        resolveStream = (text) => {
          onToken(text);
          resolve(text);
        };
      });
    });

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    // Start streaming — don't await yet.
    act(() => {
      void result.current.ask("¿Qué licitaciones hay?");
    });

    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.streaming).toBe(true);
    expect(result.current.answer).toBe("");

    // Resolve the stream with a final answer.
    await act(async () => {
      resolveStream("Aquí están las licitaciones.");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.streaming).toBe(false);
    expect(result.current.answer).toBe("Aquí están las licitaciones.");
    expect(result.current.error).toBeNull();
  });

  it("accumulates partial tokens via onToken callback", async () => {
    mockStreamAsk.mockImplementation(async ({ onToken }) => {
      onToken("Hola ");
      onToken("Hola mundo");
      return "Hola mundo";
    });

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("Saluda");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.answer).toBe("Hola mundo");
  });

  it("sets error state when streamAsk throws a non-abort error", async () => {
    mockStreamAsk.mockRejectedValue(new Error("Error 503"));

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("¿Falla el servidor?");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("Error 503");
    expect(result.current.answer).toBeNull();
    expect(result.current.streaming).toBe(false);
  });

  it("uses 'Error desconocido' for non-Error throws", async () => {
    mockStreamAsk.mockRejectedValue("string error");

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("¿Algo raro?");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("Error desconocido");
  });

  it("silently swallows AbortError (request cancelled)", async () => {
    const abortError = new DOMException("The user aborted a request.", "AbortError");
    mockStreamAsk.mockRejectedValue(abortError);

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("Pregunta cancelada");
    });

    // After an AbortError the hook returns early — no error state is set.
    expect(result.current.error).toBeNull();
  });

  it("reset() clears answer, error, streaming and loading", async () => {
    mockStreamAsk.mockRejectedValue(new Error("fallo"));

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("pregunta");
    });

    await waitFor(() => expect(result.current.error).toBe("fallo"));

    act(() => {
      result.current.reset();
    });

    expect(result.current.answer).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.streaming).toBe(false);
    expect(result.current.loading).toBe(false);
  });

  it("passes model and topK options to streamAsk", async () => {
    mockStreamAsk.mockResolvedValue("ok");

    const { result } = renderHook(() => useAsk(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.ask("pregunta", { model: "gpt-4", topK: 5 });
    });

    expect(mockStreamAsk).toHaveBeenCalledWith(
      expect.objectContaining({
        question: "pregunta",
        model: "gpt-4",
        topK: 5,
      }),
    );
  });
});

// ── useAskModels tests ─────────────────────────────────────────────────────────

describe("useAskModels", () => {
  it("returns the models array from a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse(["gpt-4", "gpt-3.5"])),
    );

    const { result } = renderHook(() => useAskModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(["gpt-4", "gpt-3.5"]);
  });

  it("extracts models from a { models: [...] } shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse({ models: ["llama3"] })),
    );

    const { result } = renderHook(() => useAskModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(["llama3"]);
  });

  it("returns [] on non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse(null, 500)),
    );

    const { result } = renderHook(() => useAskModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
