/**
 * La pantalla completa: qué pide al servidor y qué enseña sin que se lo pidan.
 *
 * Las dos reglas que fija: el orden y la página viajan en la petición (no se
 * reordena lo ya traído), y la ficha entra con la primera empresa cargada en
 * vez de con un panel que dice que no hay ninguna seleccionada.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

const { fetchWithAuth, apiMutate, setView } = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
  apiMutate: vi.fn().mockResolvedValue({}),
  setView: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth,
  apiMutate,
  ApiError: class ApiError extends Error {},
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => true }));
// El shell del espacio pinta la cabecera y el conmutador; aquí interesa el
// cuerpo, más el `?vista=` que gobierna cuál de los dos se monta.
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: "maestro", setView }),
  SpaceShell: ({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) => (
    <div>
      {actions}
      {children}
    </div>
  ),
}));

import EmpresasPage from "@/app/(dashboard)/empresas/page";

const LISTA = {
  items: [
    {
      empresa_id: 1,
      nombre_canonico: "Indra Sistemas, S.A.",
      nif_canonico: "A28599033",
      es_ute: 0,
      es_pyme: 0,
      grupo: "Indra",
      n_adjudicaciones: 148,
      importe_total: 412_000_000,
    },
    {
      empresa_id: 2,
      nombre_canonico: "Seidor, S.A.",
      nif_canonico: "A58245757",
      es_ute: 0,
      es_pyme: 1,
      grupo: null,
      n_adjudicaciones: 64,
      importe_total: 161_000_000,
    },
  ],
  limit: 12,
  offset: 0,
  total: 1284,
};

const STATS = {
  adjudicaciones_total: 5146,
  adjudicaciones_enlazadas: 4725,
  pct_filas: 93.4,
  pct_importe: 91.8,
  empresas: 1284,
  revisiones_pendientes: 8,
};

const DETALLE = {
  empresa_id: 1,
  nombre_canonico: "Indra Sistemas, S.A.",
  nif_canonico: "A28599033",
  es_ute: 0,
  es_pyme: 0,
  grupo: "Indra",
  aliases: [
    { alias_normalizado: "indra sistemas sa", nif_variante: null, fuente: "placsp" },
    { alias_normalizado: "indra", nif_variante: null, fuente: "placsp" },
  ],
  ute_miembros: [],
  participa_en_utes: [{ empresa_id: 5, nombre_canonico: "UTE Indra-Telefónica" }],
};

const PERFIL = {
  totales: {
    contratos: 148,
    importe_total: 412_000_000,
    ofertas_medias: 3.2,
    primera_adjudicacion: "2019-03-01",
    ultima_adjudicacion: "2026-07-01",
  },
  por_cpv: [{ cpv2: "72", contratos: 62, importe: 190_000_000 }],
  por_ccaa: [{ ccaa: "Madrid", contratos: 41, importe: 128_000_000 }],
  organos_principales: [
    {
      organo: "Agencia Estatal de Administración Tributaria",
      contratos: 35,
      importe: 107_000_000,
    },
  ],
  por_anio: [
    { anio: 2021, contratos: 18, importe: 42_000_000 },
    { anio: 2022, contratos: 22, importe: 58_000_000 },
  ],
};

function ruta(url: string): unknown {
  if (url.startsWith("/api/v1/empresas/stats")) return STATS;
  if (url.startsWith("/api/v1/empresas/reviews")) return { items: [] };
  if (url.startsWith("/api/v1/empresas?")) return LISTA;
  if (url.startsWith("/api/v1/competitive/empresas/")) return PERFIL;
  if (url.startsWith("/api/v1/empresas/")) return DETALLE;
  if (url.startsWith("/api/v1/competitive/watchlist")) return { items: [] };
  return {};
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}

/** URLs de `/api/v1/empresas?…` pedidas hasta ahora. */
function urlsDeLista(): string[] {
  return fetchWithAuth.mock.calls.map(([url]) => url as string).filter((url) => url.startsWith("/api/v1/empresas?"));
}

beforeEach(() => {
  fetchWithAuth.mockReset();
  fetchWithAuth.mockImplementation((url: string) => Promise.resolve(ruta(url)));
});

afterEach(() => cleanup());

describe("Empresas", () => {
  it("entra pidiendo la primera página ordenada por importe", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    await waitFor(() => expect(urlsDeLista()).not.toHaveLength(0));
    const url = urlsDeLista()[0];
    expect(url).toContain("limit=12");
    expect(url).toContain("offset=0");
    expect(url).toContain("sort=importe");
    expect(url).toContain("order=desc");
  });

  it("ordenar por una cabecera vuelve a pedir al servidor, no reordena lo traído", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    await screen.findByRole("button", { name: "Ordenar por NIF" });

    fireEvent.click(screen.getByRole("button", { name: "Ordenar por NIF" }));

    // Y entra ascendente: es una columna de texto, y el primer clic en «NIF»
    // pide el principio del alfabeto, no el final.
    await waitFor(() =>
      expect(urlsDeLista().some((url) => url.includes("sort=nif") && url.includes("order=asc"))).toBe(true),
    );
  });

  it("carga la ficha de la primera empresa sin que nadie la seleccione", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    // El nombre aparece dos veces: en la fila y como título de la ficha.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Indra Sistemas, S.A." })).toBeInTheDocument());
    expect(screen.queryByText("Ninguna empresa coincide con la búsqueda")).not.toBeInTheDocument();
  });

  it("la ficha enseña totales, trayectoria, rankings, UTEs y aliases", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    await screen.findByRole("heading", { name: "Indra Sistemas, S.A." });

    expect(screen.getByText("Contratos adjudicados")).toBeInTheDocument();
    expect(screen.getByText("Ofertas medias por licitación")).toBeInTheDocument();
    expect(screen.getByText("Trayectoria por año")).toBeInTheDocument();
    // Año completo, no «21»: abreviarlo no ahorraba ni el ancho de una barra.
    expect(screen.getByText("2021")).toBeInTheDocument();
    expect(screen.getByText("Por familia CPV")).toBeInTheDocument();
    expect(screen.getByText("Órganos principales")).toBeInTheDocument();
    // El nombre del órgano va entero: en tres columnas se cortaba a mano.
    expect(screen.getByText("Agencia Estatal de Administración Tributaria")).toBeInTheDocument();
    expect(screen.getByText("Participa en UTEs")).toBeInTheDocument();
    expect(screen.getByText(/Aliases vistos en fuente \(2\)/)).toBeInTheDocument();
  });

  it("el grupo de la ficha filtra el maestro", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    await screen.findByRole("heading", { name: "Indra Sistemas, S.A." });

    fireEvent.click(screen.getByRole("button", { name: "Grupo Indra" }));
    expect(screen.getByLabelText("Buscar empresa")).toHaveValue("Indra");
  });

  it("la línea de contexto avisa del importe resuelto bajo umbral y lleva a la cola", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    // 91,8% está por debajo del 95%: las cuotas de Competencia arrastran ese
    // error, así que es el único dato de la línea que lleva aviso.
    await waitFor(() => expect(screen.getByText("91,8%")).toBeInTheDocument());
    expect(screen.getByText("Bajo umbral")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Revisiones"));
    expect(setView).toHaveBeenCalledWith("revision");
  });

  it("los cuatro datos de contexto siguen estando, ya sin cuatro tarjetas", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    // Con `agruparSiempre`: «1284» junto a «91,8%» y a «8» eran tres formatos
    // de cifra en la misma línea.
    await waitFor(() => expect(screen.getByText("1.284")).toBeInTheDocument());
    for (const etiqueta of ["Canónicas", "Importe resuelto", "Vigiladas", "Revisiones"]) {
      expect(screen.getByText(etiqueta)).toBeInTheDocument();
    }
  });
});
