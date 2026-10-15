/**
 * Competencia › Empresas y › Revisión, montadas por la página del espacio: qué
 * piden al servidor y qué enseñan sin que se lo pidan.
 *
 * Fueron el espacio Empresas hasta 2026-10. Las reglas que fija: el orden y la
 * página viajan en la petición (no se reordena lo ya traído), la ficha entra con
 * la primera empresa cargada en vez de con un panel que dice que no hay ninguna
 * seleccionada, y esa ficha es de identidad: el análisis está en la de
 * Competencia, a la que enlaza. Y las que fija la mudanza: la línea de contexto
 * va en la cabecera solo en estas dos vistas, el contador de la cola en su
 * pestaña desde cualquiera, y la cola sigue siendo de administradores.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

const { fetchWithAuth, apiMutate, setView, estado } = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
  apiMutate: vi.fn().mockResolvedValue({}),
  setView: vi.fn(),
  estado: { vista: "empresas", admin: true },
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
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => estado.admin }));
// El shell del espacio pinta la cabecera y el conmutador; aquí interesa lo que
// la página le pasa —cuerpo, acciones, contadores y si va a sangre— y el
// `?vista=` que gobierna qué cuerpo se monta.
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: estado.vista, setView }),
  SpaceShell: ({
    children,
    actions,
    viewBadges,
    bleed,
  }: {
    children: React.ReactNode;
    actions?: React.ReactNode;
    viewBadges?: Record<string, React.ReactNode>;
    bleed?: boolean;
  }) => (
    <div data-bleed={bleed ? "si" : "no"} data-testid="espacio">
      <span data-testid="contador-revision">{viewBadges?.revision}</span>
      {actions}
      {children}
    </div>
  ),
}));
// Las vistas de análisis tienen sus suites; aquí basta con saber cuál se montó.
vi.mock("../_components/competidores-view", () => ({ default: () => <p>Vista de competidores</p> }));
vi.mock("../_components/utes-view", () => ({ default: () => <p>Vista de UTEs</p> }));

import { toast } from "sonner";
import CompetenciaPage from "@/app/(dashboard)/competencia/page";

/**
 * El cuerpo de cada vista llega con `next/dynamic`: con la suite entera en
 * paralelo, el primer `import()` de un chunk pasa del segundo por defecto.
 */
const CARGA_DE_VISTA = { timeout: 5000 };

/** La página del espacio, como la monta Next: la vista sale de `?vista=`. */
function EmpresasPage() {
  return <CompetenciaPage />;
}

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

/** Peticiones hechas hasta ahora, en orden. */
function urlsPedidas(): string[] {
  return fetchWithAuth.mock.calls.map(([url]) => url as string);
}

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
  estado.vista = "empresas";
  estado.admin = true;
  setView.mockClear();
  fetchWithAuth.mockReset();
  fetchWithAuth.mockImplementation((url: string) => Promise.resolve(ruta(url)));
});

afterEach(() => cleanup());

describe("Competencia › Empresas y Revisión", () => {
  it("las dos vistas de identidad van a sangre y traen su línea de contexto", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Canónicas", {}, CARGA_DE_VISTA)).toBeInTheDocument();
    expect(screen.getByTestId("espacio")).toHaveAttribute("data-bleed", "si");
  });

  it("en Competidores no hay línea del maestro, pero el contador de la cola sigue en su pestaña", async () => {
    estado.vista = "competidores";
    render(<EmpresasPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Vista de competidores", {}, CARGA_DE_VISTA)).toBeInTheDocument();
    expect(screen.getByTestId("espacio")).toHaveAttribute("data-bleed", "no");
    expect(screen.queryByText("Canónicas")).not.toBeInTheDocument();
    // Quien no entra en la cola también tiene que saber que hay trabajo en ella.
    await waitFor(() => expect(screen.getByTestId("contador-revision")).toHaveTextContent("8"));
    // Y no se pide el maestro: es otra vista.
    expect(urlsDeLista()).toHaveLength(0);
  });

  it("la cola sigue reservada a administradores", async () => {
    estado.vista = "revision";
    estado.admin = false;
    render(<EmpresasPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Cola reservada a administradores", {}, CARGA_DE_VISTA)).toBeInTheDocument();
    expect(urlsPedidas().some((url) => url.startsWith("/api/v1/empresas/reviews"))).toBe(false);
  });

  it("un administrador ve la cola y la pide", async () => {
    estado.vista = "revision";
    render(<EmpresasPage />, { wrapper: Wrapper });
    await waitFor(
      () => expect(urlsPedidas().some((url) => url.startsWith("/api/v1/empresas/reviews"))).toBe(true),
      CARGA_DE_VISTA,
    );
    expect(screen.queryByText("Cola reservada a administradores")).not.toBeInTheDocument();
  });
});

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

  it("la ficha es de identidad: UTEs, alias y una línea de actividad", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    await screen.findByRole("heading", { name: "Indra Sistemas, S.A." });

    expect(screen.getByText("Participa en UTEs")).toBeInTheDocument();
    expect(screen.getByText(/Alias vistos en fuente \(2\)/)).toBeInTheDocument();
    expect(await screen.findByText(/148 contratos/)).toBeInTheDocument();
    expect(screen.getByText(/activa mar 2019 → jul 2026/)).toBeInTheDocument();
    // El análisis tiene una sola ficha, la de Competencia: aquí no se repite
    // con otras cifras.
    for (const pieza of ["Trayectoria por año", "Por familia CPV", "Órganos principales", "Contratos adjudicados"]) {
      expect(screen.queryByText(pieza)).not.toBeInTheDocument();
    }
  });

  it("«Abrir ficha» lleva a la de Competencia en todo el histórico, con las mismas cifras", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    const enlace = await screen.findByRole("link", { name: "Abrir ficha" });

    // Sin `alcance=historico`, la ficha aplicaría el ámbito de la barra y no
    // enseñaría las cifras de esta línea.
    expect(enlace).toHaveAttribute("href", "/competencia/empresa/1?alcance=historico");
    // Y esta línea pide el perfil igual que esa ficha en el histórico: sin
    // filtros, así que las dos cifras salen de la misma petición.
    await waitFor(() => expect(urlsPedidas()).toContain("/api/v1/competitive/empresas/1/perfil"));
  });

  it("si el perfil falla, la ficha lo dice y sigue ofreciendo la de Competencia", async () => {
    fetchWithAuth.mockImplementation((url: string) =>
      url.startsWith("/api/v1/competitive/empresas/") ? Promise.reject(new Error("500")) : Promise.resolve(ruta(url)),
    );
    render(<EmpresasPage />, { wrapper: Wrapper });

    expect(await screen.findByText("No se pudo cargar la actividad.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir ficha" })).toBeInTheDocument();
  });

  it("«Vigilar» de la ficha es el control único y avisa de la alerta diaria", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    // Nombre exacto: el de la ficha es su texto visible; los de las filas
    // dicen «Vigilar empresa».
    const vigilar = await screen.findByRole("button", { name: "Vigilar" });
    // Un botón propio que imitara al control volvería a ser dos controles.
    expect(vigilar).toHaveAttribute("data-slot", "seguir-boton");
    // Deshabilitado hasta saber qué se vigila: pulsar a ciegas podría pedir
    // el alta de una empresa que ya estaba vigilada.
    await waitFor(() => expect(vigilar).toBeEnabled());

    fireEvent.click(vigilar);

    expect(toast).toHaveBeenCalledWith("Añadida a la vigilancia · alerta diaria");
    // Por el camino de `SeguirBoton` para empresas: el endpoint de siempre,
    // que escribe su tabla y `follows` (ADR-031 §B).
    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/competitive/watchlist", {
        empresa_id: 1,
        frequency: "daily",
      }),
    );
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

  it("«Vigiladas» lleva a la lista, que está en Competidores", async () => {
    render(<EmpresasPage />, { wrapper: Wrapper });
    await screen.findByRole("heading", { name: "Indra Sistemas, S.A." });

    // Un enlace y no un botón: sale de la pantalla, y así se puede abrir aparte.
    expect(screen.getByRole("link", { name: /Vigiladas/ })).toHaveAttribute("href", "/competencia?vista=competidores");
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
