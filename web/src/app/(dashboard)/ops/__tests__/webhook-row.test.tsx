import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Borrar un webhook rompe una integración viva del cliente y no se deshace.
 *
 * Se confirmaba con `window.confirm`, el único de la aplicación: un cuadro del
 * navegador que no sigue el tema ni el resto de la consola, donde las acciones
 * destructivas se confirman en dos pasos dentro de la propia fila.
 */

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));

import { WebhookRow } from "../_components/webhooks/webhook-row";
import type { WebhookAmpliado } from "../_hooks/use-webhooks-ambito";

const WEBHOOK = {
  id: 7,
  name: "ERP de compras",
  url: "https://erp.example.com/hook",
  event_types: ["licitacion.nueva"],
  active: true,
  formato: "json",
  failure_count: 0,
  last_triggered_at: null,
  last_status: null,
  organization_id: 1,
} as unknown as WebhookAmpliado;

function montar(editable = true) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    if (callMethod(call) === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(jsonResponse([]));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <WebhookRow webhook={WEBHOOK} editable={editable} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

function borrados(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter((c) => callMethod(c) === "DELETE");
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("WebhookRow — eliminar", () => {
  it("el primer clic solo arma la confirmación, sin window.confirm ni petición", () => {
    const confirmar = vi.spyOn(window, "confirm");
    const fetchMock = montar();

    fireEvent.click(screen.getByRole("button", { name: "Eliminar ERP de compras" }));

    expect(confirmar).not.toHaveBeenCalled();
    expect(borrados(fetchMock)).toHaveLength(0);
    expect(screen.getByRole("group", { name: "Confirmar la eliminación de ERP de compras" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancelar" }));
    confirmar.mockRestore();
  });

  it("«Cancelar» desarma sin borrar y devuelve el foco a la papelera", () => {
    const fetchMock = montar();
    const papelera = screen.getByRole("button", { name: "Eliminar ERP de compras" });

    fireEvent.click(papelera);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("group", { name: /Confirmar la eliminación/ })).toBeNull();
    expect(borrados(fetchMock)).toHaveLength(0);
    expect(document.activeElement).toBe(papelera);
  });

  it("«Sí, eliminar» borra ese webhook", async () => {
    const fetchMock = montar();
    fireEvent.click(screen.getByRole("button", { name: "Eliminar ERP de compras" }));
    fireEvent.click(screen.getByRole("button", { name: "Sí, eliminar" }));

    await waitFor(() => expect(borrados(fetchMock)).toHaveLength(1));
    // Con su organización: sin ella la API busca en la personal y, desde un
    // equipo, el borrado acababa en 404.
    expect(callUrl(borrados(fetchMock)[0])).toBe("/api/v1/webhooks/7?organization_id=1");
    await waitFor(() => expect(screen.queryByRole("group", { name: /Confirmar la eliminación/ })).toBeNull());
  });

  it("sin permiso de edición no hay papelera", () => {
    montar(false);
    expect(screen.queryByRole("button", { name: "Eliminar ERP de compras" })).toBeNull();
  });
});
