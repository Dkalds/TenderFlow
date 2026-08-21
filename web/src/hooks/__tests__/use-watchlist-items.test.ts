/**
 * Tests for web/src/hooks/use-watchlist-items.ts
 *
 * Covers: initial list fetch, optimistic add (+ rollback on error),
 * optimistic remove (+ rollback on error), and useIsWatchlisted.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import { toast } from "sonner";
import {
  useWatchlistItems,
  useAddWatchlistItem,
  useRemoveWatchlistItem,
  useIsWatchlisted,
  type WatchlistItem,
} from "@/hooks/use-watchlist-items";
import { callCredentials, callMethod, callUrl, jsonResponse } from "./fetch-call";

const WATCHLIST_ITEMS_KEY = ["watchlist-items"];

const ITEMS: WatchlistItem[] = [
  {
    id: 1,
    id_externo: "EXT-1",
    created_at: "2024-01-01T00:00:00Z",
    organization_id: null,
    visibility: null,
    titulo: "Licitación uno",
    importe: 1000,
    estado: "PUB",
    fecha_publicacion: "2024-01-01",
  },
  {
    id: 2,
    id_externo: "EXT-2",
    created_at: "2024-01-02T00:00:00Z",
    organization_id: null,
    visibility: null,
    titulo: "Licitación dos",
    importe: 2000,
    estado: "PUB",
    fecha_publicacion: "2024-01-02",
  },
];

/**
 * Doble mínimo para las mutaciones, que van por `apiMutate` (`fetch(url, init)`
 * y `res.json()`). El listado NO puede usarlo: va por el cliente tipado, que
 * lee `headers` y `text()` de la respuesta — para eso está `jsonResponse`.
 */
function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function createClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function createWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useWatchlistItems", () => {
  it("fetches the list from /api/v1/watchlist/items", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: ITEMS })));
    vi.stubGlobal("fetch", fetchMock);
    const qc = createClient();
    const { result } = renderHook(() => useWatchlistItems(), {
      wrapper: createWrapper(qc),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(ITEMS);
    const call = fetchMock.mock.calls[0];
    expect(callUrl(call)).toBe("/api/v1/watchlist/items");
    expect(callMethod(call)).toBe("GET");
    // La cookie de sesión es la única credencial: sin `include` la petición
    // sale anónima y la lista vuelve vacía en vez de fallar.
    expect(callCredentials(call)).toBe("include");
  });
});

describe("useAddWatchlistItem", () => {
  it("optimistically adds an item to the cache before the POST resolves", async () => {
    const qc = createClient();
    qc.setQueryData(WATCHLIST_ITEMS_KEY, [ITEMS[0]]);

    let resolvePost!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolvePost = resolve;
    });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockReturnValue(pending));

    const { result } = renderHook(() => useAddWatchlistItem(), {
      wrapper: createWrapper(qc),
    });

    act(() => {
      result.current.mutate("EXT-NEW");
    });

    // Cache should reflect the optimistic item immediately, before the POST resolves.
    await waitFor(() => {
      const cached = qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
      expect(cached?.some((item) => item.id_externo === "EXT-NEW")).toBe(true);
    });
    expect(cachedLength(qc)).toBe(2);

    const created: WatchlistItem = {
      id: 99,
      id_externo: "EXT-NEW",
      created_at: "2024-01-03T00:00:00Z",
      organization_id: null,
      visibility: null,
      titulo: null,
      importe: null,
      estado: null,
      fecha_publicacion: null,
    };
    resolvePost(makeResponse(created, 201));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const finalCache = qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
    expect(finalCache).toContainEqual(created);
  });

  it("rolls back the cache and shows a toast when the POST fails", async () => {
    const qc = createClient();
    qc.setQueryData(WATCHLIST_ITEMS_KEY, [ITEMS[0]]);

    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        makeResponse({ detail: "boom" }, 500),
      ),
    );

    const { result } = renderHook(() => useAddWatchlistItem(), {
      wrapper: createWrapper(qc),
    });

    act(() => {
      result.current.mutate("EXT-FAIL");
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
    expect(cached).toEqual([ITEMS[0]]);
    expect(toast.error).toHaveBeenCalledWith("No se pudo añadir a favoritos");
  });
});

describe("useRemoveWatchlistItem", () => {
  it("optimistically removes an item from the cache before the DELETE resolves", async () => {
    const qc = createClient();
    qc.setQueryData(WATCHLIST_ITEMS_KEY, ITEMS);

    let resolveDelete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveDelete = resolve;
    });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockReturnValue(pending));

    const { result } = renderHook(() => useRemoveWatchlistItem(), {
      wrapper: createWrapper(qc),
    });

    act(() => {
      result.current.mutate("EXT-1");
    });

    await waitFor(() => {
      const cached = qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
      expect(cached?.some((item) => item.id_externo === "EXT-1")).toBe(false);
    });

    resolveDelete(makeResponse(null, 204));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const finalCache = qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
    expect(finalCache).toEqual([ITEMS[1]]);
  });

  it("rolls back the cache and shows a toast when the DELETE fails", async () => {
    const qc = createClient();
    qc.setQueryData(WATCHLIST_ITEMS_KEY, ITEMS);

    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        makeResponse({ detail: "Favorito no encontrado." }, 404),
      ),
    );

    const { result } = renderHook(() => useRemoveWatchlistItem(), {
      wrapper: createWrapper(qc),
    });

    act(() => {
      result.current.mutate("EXT-1");
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
    expect(cached).toEqual(ITEMS);
    expect(toast.error).toHaveBeenCalledWith("No se pudo quitar de favoritos");
  });
});

describe("useIsWatchlisted", () => {
  it("returns true when the id_externo is present in the cached list", async () => {
    const qc = createClient();
    qc.setQueryData(WATCHLIST_ITEMS_KEY, ITEMS);
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: ITEMS }))));

    const { result } = renderHook(() => useIsWatchlisted("EXT-1"), {
      wrapper: createWrapper(qc),
    });

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("returns false when the id_externo is not present in the cached list", async () => {
    const qc = createClient();
    qc.setQueryData(WATCHLIST_ITEMS_KEY, ITEMS);
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: ITEMS }))));

    const { result } = renderHook(() => useIsWatchlisted("EXT-MISSING"), {
      wrapper: createWrapper(qc),
    });

    await waitFor(() => expect(result.current).toBe(false));
  });

  it("returns false when the list has not loaded yet", () => {
    const qc = createClient();
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));

    const { result } = renderHook(() => useIsWatchlisted("EXT-1"), {
      wrapper: createWrapper(qc),
    });

    expect(result.current).toBe(false);
  });
});

function cachedLength(qc: QueryClient): number {
  return (qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY) ?? []).length;
}
