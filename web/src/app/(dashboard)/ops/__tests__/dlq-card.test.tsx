import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * DLQ accionable (RFC ux-calidad-datos #4): la tarjeta lista lo que falló y
 * reencola una entrada sólo tras confirmar, contra el endpoint de admin. Antes
 * el botón respondía «Funcionalidad en desarrollo».
 */

import { DlqCard } from "../_components/administracion/dlq-card";

const LISTADO = {
  estado: "abiertas",
  items: [
    {
      id: 7,
      fuente: "placsp",
      scope: "atom",
      error_type: "TimeoutError",
      error_message: "read timeout",
      retry_count: 2,
      created_at: "2026-09-18T10:00:00+00:00",
    },
  ],
  resumen: [{ fuente: "placsp", scope: "atom", n: 3, retries: 2 }],
};

function montar(listado: unknown = LISTADO, status = 200) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    if (callMethod(call) === "POST") {
      return Promise.resolve(
        jsonResponse({ id: 7, estado_previo: "abierta", reencolada: true, detalle: "Reencolada" }),
      );
    }
    return Promise.resolve(jsonResponse(listado, status));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DlqCard />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DlqCard", () => {
  it("lista las entradas y cuenta las abiertas del resumen", async () => {
    montar();
    expect(await screen.findByText("placsp")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/read timeout/)).toBeInTheDocument();
  });

  it("reencola sólo después de confirmar, con POST al endpoint de admin", async () => {
    const fetchMock = montar();
    const boton = await screen.findByRole("button", { name: /Reencolar la entrada 7/ });

    fireEvent.click(boton);
    expect(fetchMock.mock.calls.some((c) => callMethod(c) === "POST")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /Confirmar reencolado de la entrada 7/ }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => callMethod(c) === "POST");
      expect(post && callUrl(post)).toBe("/api/v1/admin/dlq/7/reintentar");
    });
  });

  it("sin permisos de admin lo dice en vez de enseñar un error crudo", async () => {
    montar({ detail: "Admin required." }, 403);
    expect(
      await screen.findByText("Sólo los administradores pueden ver y reencolar la DLQ."),
    ).toBeInTheDocument();
  });
});
