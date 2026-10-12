import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// CU-29 — «Ver todas»: la bandeja completa, paginada y con filtro de lectura.

const { apiGet, apiMutate } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiMutate: vi.fn().mockResolvedValue({}),
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  // `ApiError` y compañía reales: `PanelError` los usa para el mensaje.
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet,
  apiMutate,
}));
vi.mock("@/hooks/use-organization", () => ({
  organizacionResuelta: (id: unknown) => id !== undefined,
}));

import { VerTodasSheet } from "@/components/campana/ver-todas-sheet";

function aviso(id: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    created_at: "2026-10-11T09:00:00+00:00",
    type: "pursuit_tarea_vence:1:2026-10-11",
    title: `Aviso ${id}`,
    body: `Detalle ${id}`,
    licitacion_id: null,
    rule_id: null,
    pursuit_id: null,
    read: false,
    ...extra,
  };
}

function renderSheet(onSilenciarRegla = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={qc}>
      <VerTodasSheet organizationId={7} open onOpenChange={vi.fn()} onSilenciarRegla={onSilenciarRegla} />
    </QueryClientProvider>,
  );
  return onSilenciarRegla;
}

afterEach(() => {
  apiGet.mockReset();
  apiMutate.mockClear();
});

describe("VerTodasSheet", () => {
  it("pagina con «Siguientes» y dice en qué tramo está", async () => {
    apiGet.mockImplementation(async (_ruta: string, init: { params: { query: { offset: number } } }) => ({
      items: [aviso(init.params.query.offset + 1)],
      total: 21,
      sin_leer: 21,
      limit: 20,
      offset: init.params.query.offset,
    }));
    renderSheet();

    expect(await screen.findByText("1–20 de 21")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anteriores" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Siguientes" }));

    expect(await screen.findByText("21–21 de 21")).toBeInTheDocument();
    expect(apiGet).toHaveBeenLastCalledWith(
      "/api/v1/notifications/alerts",
      expect.objectContaining({ params: { query: { organization_id: 7, estado: "todas", limit: 20, offset: 20 } } }),
    );
    expect(screen.getByRole("button", { name: "Siguientes" })).toBeDisabled();
  });

  it("un aviso sin destino se marca con su botón, y la regla se silencia desde aquí", async () => {
    apiGet.mockResolvedValue({
      items: [aviso(1), aviso(2, { rule_id: 9, title: "Regla SAP", read: true })],
      total: 2,
      sin_leer: 1,
      limit: 20,
      offset: 0,
    });
    const onSilenciar = renderSheet();

    fireEvent.click(await screen.findByRole("button", { name: "Marcar como leído" }));
    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/notifications/alerts/read", {
        ids: [1],
        organization_id: 7,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Silenciar esta regla: Regla SAP" }));
    expect(onSilenciar).toHaveBeenCalledWith(9);
  });

  it("el vacío dice qué falta según el filtro", async () => {
    apiGet.mockResolvedValue({ items: [], total: 0, sin_leer: 0, limit: 20, offset: 0 });
    renderSheet();

    expect(await screen.findByText("No tienes avisos en esta organización")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Sin leer/ }));
    expect(await screen.findByText("Lo tienes todo leído")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Marcar todo como leído" })).not.toBeInTheDocument();
  });

  it("un fallo se pinta en línea con «Reintentar»", async () => {
    apiGet.mockRejectedValue(new Error("caída"));
    renderSheet();

    expect(await screen.findByText("No se pudieron cargar tus avisos")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
