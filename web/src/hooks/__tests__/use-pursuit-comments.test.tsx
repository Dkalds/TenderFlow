import * as React from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import {
  COMMENTS_PAGE_SIZE,
  useAddPursuitComment,
  useDeletePursuitComment,
  usePursuitComments,
} from "@/hooks/use-pursuit-comments";
import { useOrganizationStore } from "@/hooks/use-organization";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

const organization = {
  id: 1,
  name: "Equipo",
  is_personal: true,
  role: "owner",
  created_at: "2026-07-30T10:00:00Z",
};

const comment = {
  id: 3,
  pursuit_id: 7,
  organization_id: 1,
  author_user_id: 5,
  author_name: "Ana",
  body: "hola",
  created_at: "2026-09-01T10:00:00Z",
  can_delete: true,
};

const thread = {
  pursuit_id: 7,
  organization_id: 1,
  items: [comment],
  total: 1,
  limit: COMMENTS_PAGE_SIZE,
  offset: 0,
};

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** `fetch` doblado: organizaciones, hilo o lo que indique `mutation`. */
function stubFetch(mutation: (call: readonly unknown[]) => Response | undefined = () => undefined) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    if (callUrl(call).includes("/organizations")) return Promise.resolve(jsonResponse([organization]));
    const forced = mutation(call);
    return Promise.resolve(forced ?? jsonResponse(thread));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  useOrganizationStore.setState({ activeOrganizationId: null });
  vi.unstubAllGlobals();
});

describe("pursuit comment hooks", () => {
  it("loads the thread scoped to the active organization and with the page size", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    const fetchMock = stubFetch();

    const { result } = renderHook(() => usePursuitComments(7), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items?.[0]?.body).toBe("hola");
    const url = fetchMock.mock.calls.map(callUrl).find((candidate) => candidate.includes("/comments"));
    expect(url).toContain("/api/v1/pursuits/7/comments");
    expect(url).toContain("organization_id=1");
    expect(url).toContain(`limit=${COMMENTS_PAGE_SIZE}`);
  });

  it("does not ask for the thread without an opportunity", () => {
    const fetchMock = stubFetch();

    const { result } = renderHook(() => usePursuitComments(null), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock.mock.calls.map(callUrl).some((url) => url.includes("/comments"))).toBe(false);
  });

  it("posts the draft with its idempotency key in the header, not the body", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    const fetchMock = stubFetch((call) =>
      callMethod(call) === "POST" ? jsonResponse(comment, 201) : undefined,
    );

    const { result } = renderHook(() => useAddPursuitComment(7), { wrapper });
    const created = await result.current.mutateAsync({ body: "hola", idempotencyKey: "draft-1" });

    expect(created.id).toBe(3);
    const post = fetchMock.mock.calls.find((call) => callMethod(call) === "POST");
    expect(post).toBeDefined();
    expect(callUrl(post!)).toBe("/api/v1/pursuits/7/comments?organization_id=1");
    const init = post![1] as RequestInit;
    expect(new Headers(init.headers).get("X-Idempotency-Key")).toBe("draft-1");
    // La clave viaja en la cabecera, nunca en el cuerpo: la API la rechazaría
    // (`extra="forbid"`).
    expect(JSON.parse(String(init.body))).toEqual({ body: "hola" });
  });

  it("deletes a comment and accepts the empty 204 body", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 1 });
    const fetchMock = stubFetch((call) =>
      callMethod(call) === "DELETE" ? new Response(null, { status: 204 }) : undefined,
    );

    const { result } = renderHook(() => useDeletePursuitComment(7), { wrapper });

    await expect(result.current.mutateAsync(3)).resolves.toBeUndefined();
    const del = fetchMock.mock.calls.find((call) => callMethod(call) === "DELETE");
    expect(del).toBeDefined();
    expect(callUrl(del!)).toBe("/api/v1/pursuits/7/comments/3?organization_id=1");
  });
});
