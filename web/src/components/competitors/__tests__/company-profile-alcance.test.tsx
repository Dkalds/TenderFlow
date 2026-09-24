/**
 * El alcance del dossier: «Tu ámbito» o «Todo el histórico».
 *
 * Fija qué manda la ficha al servidor en cada caso —el ámbito de la barra o
 * nada— y que el modo viaja en la URL, que es lo que permite enlazar la ficha
 * entera desde otra pantalla. Resumen, listado y «Contra mí» van con dobles:
 * aquí importa lo que se pide, no cómo se pintan las cifras.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { TooltipProvider } from "@/components/ui/tooltip";

const { fetchWithAuth } = vi.hoisted(() => ({ fetchWithAuth: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento: vi.fn(),
}));
vi.mock("@/hooks/use-seguimiento", () => ({
  useSeguimiento: () => ({
    ids: new Set<string>(),
    sigue: () => false,
    alternar: vi.fn(() => true),
    seguir: vi.fn(),
    dejar: vi.fn(),
    isLoading: false,
    enVuelo: false,
  }),
}));
vi.mock("@/components/competitors/company-profile-summary", () => ({
  CompanyProfileSummary: () => <p>resumen</p>,
}));
vi.mock("@/components/competitors/company-awards", () => ({
  CompanyAwards: ({ scopeQuery }: { scopeQuery: string }) => <p data-testid="adjudicaciones">{scopeQuery}</p>,
}));
vi.mock("@/components/competitors/company-contra-mi", () => ({ CompanyContraMi: () => <p>contra mí</p> }));
// La pestaña Identidad se carga con `next/dynamic`; su contenido tiene su
// propio test. Aquí basta con ver qué identidades le llegan.
vi.mock("next/dynamic", () => ({
  default:
    () =>
    ({ empresaIds }: { empresaIds: number[] }) => <p>identidad de {empresaIds.join(",")}</p>,
}));

import { CompanyProfile } from "../company-profile";
import type { CompanyProfileData } from "../company-profile-types";

/** Sólo los campos que lee la ficha fuera del resumen y del listado. */
function perfil(contratos: number): CompanyProfileData {
  return {
    empresa: { empresa_id: 7, nombre: "Ejemplo Digital", nif: null, es_ute: false, grupo: null },
    actividad_historica: {
      contratos: 8,
      importe_total: 900_000,
      primera_adjudicacion: "2022-01-01",
      ultima_adjudicacion: "2025-10-01",
    },
    totales: { contratos, organos: 2 },
    participaciones_ute: [],
  } as unknown as CompanyProfileData;
}

function renderFicha({
  search = "",
  groupIds,
  contratos = 4,
}: { search?: string; groupIds?: number[]; contratos?: number } = {}) {
  fetchWithAuth.mockImplementation((url: string) => Promise.resolve(url.includes("/perfil") ? perfil(contratos) : {}));
  const onUrlUpdate = vi.fn();
  const Nuqs = withNuqsTestingAdapter({ searchParams: search, onUrlUpdate });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <Nuqs>
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <CompanyProfile empresaId={7} groupIds={groupIds} />
        </TooltipProvider>
      </QueryClientProvider>
    </Nuqs>,
  );
  return { onUrlUpdate };
}

/** Parámetros de cada petición del perfil, en el orden en que salieron. */
function peticionesPerfil(): URLSearchParams[] {
  return fetchWithAuth.mock.calls
    .map(([url]) => url as string)
    .filter((url) => url.includes("/perfil"))
    .map((url) => new URL(url, "http://x").searchParams);
}

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("CompanyProfile · alcance", () => {
  it("por defecto aplica el ámbito de la barra y deja elegir periodo", async () => {
    renderFicha({ search: "?ccaa=Madrid&tecnologia=SAP" });
    await screen.findByRole("heading", { name: "Ejemplo Digital" });

    const [primera] = peticionesPerfil();
    expect(primera.get("ccaa")).toBe("Madrid");
    expect(primera.get("tecnologia")).toBe("SAP");
    expect(screen.getByRole("button", { name: "Tu ámbito" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("group", { name: "Periodo" })).toBeInTheDocument();
  });

  it("«Todo el histórico» pide la actividad entera, lo dice y lo deja en la URL", async () => {
    const { onUrlUpdate } = renderFicha({ search: "?ccaa=Madrid&tecnologia=SAP&fecha_desde=2025-01-01" });
    await screen.findByRole("heading", { name: "Ejemplo Digital" });
    // Con fechas en la barra, «Tu ámbito» arranca en «Filtro global».
    expect(peticionesPerfil()[0].get("fecha_desde")).toBe("2025-01-01");

    fireEvent.click(screen.getByRole("button", { name: "Todo el histórico" }));

    await waitFor(() => expect(peticionesPerfil()).toHaveLength(2));
    const historico = peticionesPerfil()[1];
    for (const clave of ["ccaa", "tecnologia", "importe_min", "fecha_desde", "fecha_hasta"]) {
      expect(historico.has(clave)).toBe(false);
    }
    // La barra sigue enseñando sus filtros: la ficha tiene que decir que no los usa.
    expect(screen.getByText(/sin los filtros del ámbito ni fechas/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Periodo" })).not.toBeInTheDocument();

    await waitFor(() => expect(onUrlUpdate).toHaveBeenCalled());
    const url = onUrlUpdate.mock.calls.at(-1)![0].searchParams as URLSearchParams;
    expect(url.get("alcance")).toBe("historico");
    // El ámbito global no se toca: sigue ahí para el resto de pantallas.
    expect(url.get("ccaa")).toBe("Madrid");
  });

  it("un enlace con ?alcance=historico entra ya en el histórico", async () => {
    renderFicha({ search: "?ccaa=Madrid&alcance=historico" });
    await screen.findByRole("heading", { name: "Ejemplo Digital" });

    expect(peticionesPerfil()).toHaveLength(1);
    expect(peticionesPerfil()[0].has("ccaa")).toBe(false);
    expect(screen.getByRole("button", { name: "Todo el histórico" })).toHaveAttribute("aria-pressed", "true");
  });

  it("el grupo viaja en los dos alcances, y el listado pide lo mismo que el perfil", async () => {
    renderFicha({ search: "?ccaa=Madrid", groupIds: [8] });
    await screen.findByRole("heading", { name: "Ejemplo Digital" });
    expect(peticionesPerfil()[0].get("empresa_ids")).toBe("7,8");

    fireEvent.click(screen.getByRole("button", { name: "Todo el histórico" }));

    await waitFor(() => expect(peticionesPerfil()).toHaveLength(2));
    expect(peticionesPerfil()[1].get("empresa_ids")).toBe("7,8");
    const listado = new URLSearchParams(screen.getByTestId("adjudicaciones").textContent ?? "");
    expect(listado.get("empresa_ids")).toBe("7,8");
    expect(listado.has("ccaa")).toBe(false);
  });

  it("sin actividad en el ámbito ofrece saltar al histórico", async () => {
    renderFicha({ search: "?ccaa=Madrid", contratos: 0 });
    await screen.findByText("Sin adjudicaciones dentro de este ámbito");

    fireEvent.click(screen.getByRole("button", { name: "Ver todo el histórico" }));

    await waitFor(() => expect(peticionesPerfil()).toHaveLength(2));
    expect(peticionesPerfil()[1].has("ccaa")).toBe(false);
    // En el histórico el vacío ya no es «de este ámbito»: no hay ámbito.
    expect(await screen.findByText("Sin adjudicaciones propias")).toBeInTheDocument();
  });

  it("la pestaña Identidad recibe todas las identidades del grupo", async () => {
    renderFicha({ groupIds: [8] });
    await screen.findByRole("heading", { name: "Ejemplo Digital" });

    fireEvent.click(screen.getByRole("tab", { name: "Identidad" }));

    expect(await screen.findByText("identidad de 7,8")).toBeInTheDocument();
  });
});
