/**
 * F5.4 — la banda «qué cambió desde tu última visita».
 *
 * Fija lo que el plan pide de la pantalla: que la petición lleve la
 * organización activa (sin ella no entran las oportunidades del equipo), que
 * cero ítems sea una banda que lo dice y no un hueco, que el recorte de la
 * ventana se declare, y que la telemetría salga una vez con `banda`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { apiGet, apiMutate, registrarEvento } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiMutate: vi.fn(),
  registrarEvento: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({ apiGet, apiMutate }));
vi.mock("@/lib/analytics", () => ({ registrarEvento }));
vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 21 }));

import { DesdeUltimaVisita } from "../desde-ultima-visita";

function renderBanda() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <DesdeUltimaVisita />
    </QueryClientProvider>,
  );
}

function novedad(i: number, extra: Record<string, unknown> = {}) {
  return {
    subtipo: "plazo_ampliado",
    titulo: `Plazo ampliado en expediente ${i}`,
    detalle: "Nueva fecha límite: 30/09/2026.",
    licitacion_id: `ES-${i}`,
    cuando: "2026-09-17T10:00:00+00:00",
    ...extra,
  };
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  apiMutate.mockReset();
  registrarEvento.mockReset();
});

describe("DesdeUltimaVisita", () => {
  it("pide el diff con la organización activa y enlaza cada cambio a su expediente", async () => {
    apiGet.mockResolvedValue({
      desde: "2026-09-16T08:00:00+00:00",
      items: [novedad(1), novedad(2, { subtipo: "pursuit", titulo: "Tu equipo movió «Soporte SAP»" })],
      por_subtipo: { plazo_ampliado: 1, pursuit: 1 },
      ventana_recortada: false,
    });
    renderBanda();

    expect(await screen.findByText(/2 cambios en lo que sigues desde el/)).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/analytics/resumen/desde-mi-ultima-visita", {
      params: { query: { organization_id: 21 } },
    });
    expect(screen.getByText("Plazo ampliado en expediente 1").closest("a")).toHaveAttribute(
      "href",
      "/detalle?lic=ES-1",
    );
    expect(screen.getByText("Tu equipo movió «Soporte SAP»")).toBeInTheDocument();
    expect(screen.queryByText(/no se mira más atrás/)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(registrarEvento).toHaveBeenCalledWith("espacio_abierto", {
        espacio: "resumen",
        origen: "pantalla",
        banda: "desde_ultima_visita",
      }),
    );
    expect(registrarEvento).toHaveBeenCalledTimes(1);
  });

  it("cero ítems pinta una banda que lo dice", async () => {
    apiGet.mockResolvedValue({
      desde: "2026-09-16T08:00:00+00:00",
      items: [],
      por_subtipo: {},
      ventana_recortada: false,
    });
    renderBanda();

    expect(await screen.findByText(/Sin cambios en lo que sigues desde el/)).toBeInTheDocument();
    expect(screen.getByRole("region")).toBeInTheDocument();
    // Sin cambios no hay nada que marcar.
    expect(screen.queryByRole("button", { name: /Marcar todo como visto/ })).not.toBeInTheDocument();
  });

  it("«marcar todo como visto» mueve la marca y vuelve a pedir la banda", async () => {
    apiGet
      .mockResolvedValueOnce({
        desde: "2026-09-16T08:00:00+00:00",
        items: [novedad(1)],
        por_subtipo: { plazo_ampliado: 1 },
        ventana_recortada: false,
      })
      .mockResolvedValue({
        desde: "2026-09-19T10:00:00+00:00",
        items: [],
        por_subtipo: {},
        ventana_recortada: false,
      });
    apiMutate.mockResolvedValue({ visto_en: "2026-09-19T10:00:00+00:00" });
    renderBanda();

    fireEvent.click(await screen.findByRole("button", { name: /Marcar todo como visto/ }));

    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/analytics/resumen/desde-mi-ultima-visita/visto"),
    );
    expect(await screen.findByText(/Sin cambios en lo que sigues desde el/)).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("declara el recorte de la ventana y pliega lo que no cabe", async () => {
    apiGet.mockResolvedValue({
      desde: "2026-09-04T08:00:00+00:00",
      items: [1, 2, 3, 4, 5, 6].map((i) => novedad(i)),
      por_subtipo: { plazo_ampliado: 6 },
      ventana_recortada: true,
    });
    renderBanda();

    expect(await screen.findByText(/no se mira más atrás/)).toBeInTheDocument();
    expect(screen.getByText("Ver 2 más")).toBeInTheDocument();
  });
});
