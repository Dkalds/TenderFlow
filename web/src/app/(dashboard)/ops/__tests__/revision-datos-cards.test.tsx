import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Colas de revisión del dato y auditoría de verdad (Ops › Datos).
 *
 * Las dos colas se llenaban solas —el detector de duplicados y el resolver de
 * órganos dejan lo dudoso para una persona— y no había dónde vaciarlas. La
 * auditoría solo llegaba por correo. Lo que se fija aquí: cada decisión pide
 * confirmación antes de ir a la API, una sola a la vez, y el «sin permisos» se
 * dice en el panel.
 */

import { RevisionDuplicadosCard } from "../_components/calidad-datos/revision-duplicados-card";
import { RevisionOrganosCard } from "../_components/calidad-datos/revision-organos-card";
import { VerdadDominioCard } from "../_components/calidad-datos/verdad-dominio-card";

const DUPLICADOS = {
  total: 1,
  items: [
    {
      licitacion_id: "ted:123-2026",
      canonical_id: "EXP-1",
      clave_match: "clave",
      confianza: 0.8,
      titulo: "Soporte SAP (TED)",
      fuente: "ted",
      organo: "Servicio de Salud",
      fecha_publicacion: "2026-09-01",
      importe: 100000,
      titulo_canonica: "Soporte SAP",
      fuente_canonica: "placsp",
      organo_canonica: "Servicio de Salud",
      fecha_publicacion_canonica: "2026-08-30",
      importe_canonica: 100000,
    },
  ],
};

const ORGANOS = {
  total: 1,
  items: [
    {
      id: 4,
      nombre_original: "Ayto. Villanueva",
      alias_normalizado: "ayto villanueva",
      candidato_organo_id: 9,
      candidato_nombre: "Ayuntamiento de Villanueva",
      score: 0.9,
    },
  ],
};

const VERDAD = {
  medido_en: "2026-10-23T08:00:00+00:00",
  violaciones: ["UTE: 9% de las adjudicaciones parecen una UTE expandida"],
  secciones: [
    {
      clave: "ute",
      titulo: "Adjudicaciones con pinta de UTE contada varias veces",
      estado: "violacion",
      metricas: [{ etiqueta: "Filas afectadas", valor: 9, unidad: "%", limite: 0.02, supera: true }],
    },
    {
      clave: "fechas_iso",
      titulo: "Fechas de texto que no son ISO-8601",
      estado: "error",
      metricas: [],
      error: "statement timeout",
    },
  ],
};

function montar(nodo: React.ReactNode, listado: unknown, status = 200, resultado: unknown = {}) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) =>
    Promise.resolve(callMethod(call) === "POST" ? jsonResponse(resultado) : jsonResponse(listado, status)),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{nodo}</TooltipProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

function cuerpoDelPost(fetchMock: ReturnType<typeof vi.fn>): unknown {
  const post = fetchMock.mock.calls.find((c) => callMethod(c) === "POST");
  const init = post?.[1] as RequestInit | undefined;
  return init?.body ? JSON.parse(String(init.body)) : undefined;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RevisionDuplicadosCard", () => {
  it("enseña las dos filas del par y lo confirma sólo tras pedir confirmación", async () => {
    const fetchMock = montar(<RevisionDuplicadosCard />, DUPLICADOS, 200, {
      licitacion_id: "ted:123-2026",
      estado: "confirmed",
      detalle: "Confirmado",
    });

    expect(await screen.findByText("Soporte SAP (TED)")).toBeInTheDocument();
    expect(screen.getByText("Soporte SAP")).toBeInTheDocument();
    expect(screen.getByText("1 pendientes")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Es el mismo: ted:123-2026" }));
    expect(fetchMock.mock.calls.some((c) => callMethod(c) === "POST")).toBe(false);
    // Armada una decisión, la otra no se ofrece.
    expect(screen.queryByRole("button", { name: "No es el mismo: ted:123-2026" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Confirmar: es el mismo/ }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => callMethod(c) === "POST");
      expect(post && callUrl(post)).toBe("/api/v1/admin/revision/duplicados/ted%3A123-2026/resolver");
    });
    expect(cuerpoDelPost(fetchMock)).toEqual({ aceptar: true });
  });

  it("rechazar manda aceptar=false", async () => {
    const fetchMock = montar(<RevisionDuplicadosCard />, DUPLICADOS, 200, {
      licitacion_id: "ted:123-2026",
      estado: "rejected",
      detalle: "Rechazado",
    });
    fireEvent.click(await screen.findByRole("button", { name: "No es el mismo: ted:123-2026" }));
    fireEvent.click(screen.getByRole("button", { name: /Confirmar: no es el mismo/ }));
    await waitFor(() => expect(cuerpoDelPost(fetchMock)).toEqual({ aceptar: false }));
  });

  it("sin nada pendiente lo dice", async () => {
    montar(<RevisionDuplicadosCard />, { total: 0, items: [] });
    expect(await screen.findByText("No hay nada pendiente")).toBeInTheDocument();
  });

  it("sin permisos de admin lo dice en vez de enseñar un error crudo", async () => {
    montar(<RevisionDuplicadosCard />, { detail: "Admin required." }, 403);
    expect(await screen.findByText("Sólo los administradores pueden revisar los duplicados.")).toBeInTheDocument();
  });
});

describe("RevisionOrganosCard", () => {
  it("separa una grafía sólo tras confirmar, con POST a su revisión", async () => {
    const fetchMock = montar(<RevisionOrganosCard />, ORGANOS, 200, {
      id: 4,
      estado: "rejected",
      organo_id: 12,
      organo_nuevo: true,
      filas_asignadas: 3,
      detalle: "Queda como órgano propio; 3 licitaciones asignadas.",
    });

    expect(await screen.findByText("Ayuntamiento de Villanueva")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Es otro órgano: Ayto. Villanueva" }));
    expect(fetchMock.mock.calls.some((c) => callMethod(c) === "POST")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /Confirmar: es otro órgano/ }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => callMethod(c) === "POST");
      expect(post && callUrl(post)).toBe("/api/v1/admin/revision/organos/4/resolver");
    });
    expect(cuerpoDelPost(fetchMock)).toEqual({ aceptar: false });
  });

  it("sin candidato no ofrece juntarla con nadie", async () => {
    montar(<RevisionOrganosCard />, {
      total: 1,
      items: [{ ...ORGANOS.items[0], candidato_organo_id: null, candidato_nombre: null }],
    });
    expect(await screen.findByRole("button", { name: "Es otro órgano: Ayto. Villanueva" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Es el mismo: Ayto. Villanueva" })).not.toBeInTheDocument();
  });

  it("sin nada pendiente lo dice", async () => {
    montar(<RevisionOrganosCard />, { total: 0, items: [] });
    expect(await screen.findByText("No hay nada pendiente")).toBeInTheDocument();
  });
});

describe("VerdadDominioCard", () => {
  it("marca la sección fuera de rango y dice cuál no se pudo medir", async () => {
    montar(<VerdadDominioCard />, VERDAD);

    expect(
      await screen.findByRole("heading", { name: "Adjudicaciones con pinta de UTE contada varias veces" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fuera de rango")).toBeInTheDocument();
    expect(screen.getByText("Sin medir")).toBeInTheDocument();
    expect(screen.getByText("No se pudo medir: statement timeout")).toBeInTheDocument();
    expect(screen.getByText("1 avisos fuera de rango")).toBeInTheDocument();
  });

  it("sin permisos de admin lo dice", async () => {
    montar(<VerdadDominioCard />, { detail: "Admin required." }, 403);
    expect(await screen.findByText("Sólo los administradores pueden ver la auditoría del dato.")).toBeInTheDocument();
  });
});
