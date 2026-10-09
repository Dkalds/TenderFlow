/**
 * La pestaña «Actividad del equipo» lee el feed de `GET /pursuits/actividad`.
 *
 * Antes era un texto que mandaba al Resumen y el endpoint no lo llamaba nadie.
 * Lo que fija este suite: la petición lleva organización, persona y cursor; las
 * páginas se acumulan con el cursor que da el backend; ningún evento se
 * descarta por no tener nombre legible ni actor; cada línea dice qué cambió;
 * y la persona filtrada vive en la URL.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { apiGet, miembros } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  miembros: { data: [] as unknown[] },
}));

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));
import { irA } from "@/test/navegacion-superficial";

vi.mock("@/lib/api-client", () => ({ apiGet }));
vi.mock("@/hooks/use-organization", () => ({
  // Réplica de la real: `undefined` es «todavía no se sabe»; `null`, «no hay
  // ninguna», que sí es una respuesta y deja pasar la consulta.
  organizacionResuelta: (id: unknown) => id !== undefined,
  useOrganizationMembers: () => miembros,
}));

import { ActividadEquipo } from "@/app/(dashboard)/direccion/_components/actividad-equipo";
import { etiquetaCambio, verboDeEvento } from "@/app/(dashboard)/direccion/_lib/actividad";

function item(id: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    pursuit_id: 100 + id,
    licitacion_id: `ES-${id}`,
    titulo: `Servicio SAP ${id}`,
    evento: "pursuit.updated",
    actor: "Ana López",
    cuando: "2026-09-08T19:30:44+00:00",
    ...extra,
  };
}

function renderActividad() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <ActividadEquipo organizationId={21} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  miembros.data = [];
  irA("/direccion?vista=actividad");
});

describe("ActividadEquipo", () => {
  it("pide el feed de la organización activa y pinta quién hizo qué", async () => {
    apiGet.mockResolvedValue({
      organization_id: 21,
      items: [item(2, { evento: "pursuit.created" }), item(1, { actor: null })],
      siguiente_cursor: null,
      filtrado_por_rol: false,
    });

    renderActividad();

    expect(await screen.findByText("abrió la oportunidad")).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/pursuits/actividad", {
      params: { query: { organization_id: 21, usuario: undefined, antes_de_id: undefined, limit: 50 } },
    });
    expect(screen.getByRole("link", { name: "Servicio SAP 2" }).getAttribute("href")).toBe(
      "/oportunidades/102",
    );
    // Una cuenta dada de baja deja el evento sin actor: se dice, no se inventa.
    expect(screen.getByText("Alguien del equipo")).toBeTruthy();
    expect(screen.getByText("No hay actividad anterior.")).toBeTruthy();
  });

  it("«Cargar más» pide la página siguiente con el cursor del backend y la acumula", async () => {
    apiGet
      .mockResolvedValueOnce({ organization_id: 21, items: [item(60)], siguiente_cursor: 60, filtrado_por_rol: false })
      .mockResolvedValueOnce({ organization_id: 21, items: [item(12)], siguiente_cursor: null, filtrado_por_rol: false });

    renderActividad();

    fireEvent.click(await screen.findByRole("button", { name: "Cargar más" }));

    expect(await screen.findByText("Servicio SAP 12")).toBeTruthy();
    expect(screen.getByText("Servicio SAP 60")).toBeTruthy();
    expect(apiGet).toHaveBeenLastCalledWith("/api/v1/pursuits/actividad", {
      params: { query: { organization_id: 21, usuario: undefined, antes_de_id: 60, limit: 50 } },
    });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Cargar más" })).toBeNull());
  });

  it("sin eventos lo dice en vez de dejar la pestaña en blanco", async () => {
    apiGet.mockResolvedValue({ organization_id: 21, items: [], siguiente_cursor: null, filtrado_por_rol: false });

    renderActividad();

    expect(await screen.findByText("Sin actividad")).toBeTruthy();
  });

  it("el filtro por persona solo aparece cuando hay a quién filtrar", async () => {
    apiGet.mockResolvedValue({ organization_id: 21, items: [item(1)], siguiente_cursor: null, filtrado_por_rol: false });
    miembros.data = [{ user_id: 1, display_name: "Ana López", status: "active" }];

    renderActividad();
    await screen.findByText("Servicio SAP 1");
    expect(screen.queryByLabelText("Filtrar por persona")).toBeNull();

    cleanup();
    miembros.data = [
      { user_id: 1, display_name: "Ana López", status: "active" },
      { user_id: 2, display_name: "Luis Pérez", status: "active" },
    ];
    renderActividad();
    expect(await screen.findByLabelText("Filtrar por persona")).toBeTruthy();
  });
});

describe("lo que cambió", () => {
  it("la línea dice qué cambió y los eventos se agrupan por día", async () => {
    apiGet.mockResolvedValue({
      organization_id: 21,
      items: [
        item(3, {
          cambios: [
            { campo: "status", desde: "preparing", hasta: "submitted" },
          ],
        }),
        item(2, {
          cuando: "2026-09-01T10:00:00+00:00",
          cambios: [
            { campo: "outcome", desde: "pending", hasta: "lost" },
            { campo: "outcome_reason_code", desde: null, hasta: "precio" },
          ],
        }),
      ],
      siguiente_cursor: null,
      filtrado_por_rol: false,
    });

    renderActividad();

    expect(await screen.findByText("movió")).toBeTruthy();
    expect(screen.getByText("Etapa: Preparando oferta → Presentada")).toBeTruthy();
    expect(screen.getByText("marcó como perdida")).toBeTruthy();
    expect(screen.getByText("Motivo: Precio")).toBeTruthy();
    // Dos días distintos, dos encabezados.
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(2);
  });

  it("la persona filtrada sale de la URL y viaja en la petición", async () => {
    irA("/direccion?vista=actividad&persona=7");
    apiGet.mockResolvedValue({ organization_id: 21, items: [], siguiente_cursor: null, filtrado_por_rol: false });

    renderActividad();

    expect(await screen.findByText("Esta persona todavía no ha movido ninguna oportunidad.")).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/pursuits/actividad", {
      params: { query: { organization_id: 21, usuario: 7, antes_de_id: undefined, limit: 50 } },
    });
  });
});

describe("verboDeEvento", () => {
  it("un tipo desconocido se enseña con su nombre técnico, no se pierde", () => {
    expect(verboDeEvento("pursuit.archived")).toBe("pursuit.archived");
    expect(verboDeEvento("checklist_evaluated")).toBe("evaluó el go/no-go de");
  });

  it("el resultado manda sobre la etapa, y la etapa sobre el tipo", () => {
    const etapa = { campo: "status" as const, desde: "preparing", hasta: "won" };
    expect(verboDeEvento("pursuit.updated", [etapa, { campo: "outcome", desde: "pending", hasta: "won" }])).toBe(
      "marcó como ganada",
    );
    expect(verboDeEvento("pursuit.updated", [etapa])).toBe("movió");
    expect(verboDeEvento("pursuit.updated", [{ campo: "decision", desde: "pending", hasta: "no_go" }])).toBe(
      "decidió NO-GO en",
    );
  });

  it("un valor desconocido se enseña tal cual", () => {
    expect(etiquetaCambio({ campo: "status", desde: "identified", hasta: "archivada" })).toBe(
      "Etapa: Identificada → archivada",
    );
  });
});
