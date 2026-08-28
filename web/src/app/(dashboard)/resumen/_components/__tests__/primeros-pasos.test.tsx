import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * La banda de primeros pasos sólo vale si se apaga sola. Lo que estos tests
 * fijan no es el marcado: es que el estado venga del servidor y que ningún
 * estado intermedio se lea como una carencia del usuario.
 *
 * Se dobla el cliente tipado entero y se responde por ruta, que es como se
 * comporta de verdad: así el test ejercita también el gateo por `organizations`
 * y las tres señales a la vez.
 */

interface RespuestasFalsas {
  perfil: unknown;
  reglas: unknown;
  pursuits: unknown;
  organizations: unknown;
  /** Rutas que deben fallar, para el caso «no se puede comprobar». */
  fallan: Set<string>;
  /** Rutas que nunca resuelven, para el caso «todavía cargando». */
  cuelgan: Set<string>;
}

const backend = vi.hoisted(
  () =>
    ({
      perfil: {},
      reglas: { items: [] },
      pursuits: { items: [], total: 0, limit: 50, offset: 0, organization_id: 1 },
      organizations: [{ id: 1, name: "Acme", role: "owner" }],
      fallan: new Set<string>(),
      cuelgan: new Set<string>(),
    }) as RespuestasFalsas,
);

const apiGet = vi.hoisted(() =>
  vi.fn((path: string) => {
    if (backend.cuelgan.has(path)) return new Promise(() => {});
    if (backend.fallan.has(path)) return Promise.reject(new Error("boom"));
    if (path === "/api/v1/me/profile") return Promise.resolve(backend.perfil);
    if (path === "/api/v1/watchlist/rules") return Promise.resolve(backend.reglas);
    if (path === "/api/v1/pursuits") return Promise.resolve(backend.pursuits);
    if (path === "/api/v1/organizations") return Promise.resolve(backend.organizations);
    return Promise.reject(new Error(`ruta no doblada: ${path}`));
  }),
);

vi.mock("@/lib/api-client", () => ({
  apiGet,
  apiMutate: vi.fn(),
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

vi.mock("@/lib/analytics", () => ({
  primeraVez: () => false,
  registrarEvento: vi.fn(),
}));

import { PrimerosPasos } from "@/app/(dashboard)/resumen/_components/primeros-pasos";
import { estaDescartado } from "@/components/onboarding/descarte";
import { registrarEvento } from "@/lib/analytics";

const eventos = vi.mocked(registrarEvento);

const PERFIL_HECHO = {
  weights: { importe: 100 },
  afinidad_keywords: ["SAP"],
  updated_at: "2026-08-01T00:00:00Z",
  visibility: "private",
};
const REGLA_ACTIVA = {
  items: [{ id: 1, active: true, email: null, frequency: "daily", match_count: 3 }],
};

function renderBanda(props: { onDescartar?: () => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <PrimerosPasos {...props} />
    </QueryClientProvider>,
  );
}

/** Espera a que las tres señales hayan resuelto: el progreso deja de tener incógnitas. */
function esperarResuelto(hechos: number) {
  return screen.findByText(`${hechos} de 3 hechos`);
}

function filaDe(titulo: string): HTMLElement {
  const fila = screen.getByText(titulo).closest("li");
  if (!fila) throw new Error(`sin fila para «${titulo}»`);
  return fila;
}

function rutasPedidas(): string[] {
  return apiGet.mock.calls.map((call) => call[0]);
}

/**
 * Ausencia comprobada, no ausencia por llegar antes: `findBy*` agota su ventana
 * antes de rechazar, así que esto sí distingue «no sale» de «todavía no salió».
 */
async function noApareceLaBanda(): Promise<void> {
  await expect(
    screen.findByRole("heading", { name: "Primeros pasos" }, { timeout: 400 }),
  ).rejects.toThrow();
}

describe("PrimerosPasos", () => {
  beforeEach(() => {
    cleanup();
    window.localStorage.clear();
    apiGet.mockClear();
    eventos.mockClear();
    backend.perfil = {};
    backend.reglas = { items: [] };
    backend.pursuits = { items: [], total: 0, limit: 50, offset: 0, organization_id: 1 };
    backend.organizations = [{ id: 1, name: "Acme", role: "owner" }];
    backend.fallan = new Set();
    backend.cuelgan = new Set();
  });

  it("con una cuenta recién creada saca los tres pasos y adónde va cada uno", async () => {
    renderBanda();
    expect(await screen.findByRole("heading", { name: "Primeros pasos" })).toBeInTheDocument();
    await esperarResuelto(0);

    for (const [titulo, destino] of [
      ["Ajusta tu perfil de scoring", "/mi-perfil"],
      ["Crea una regla de vigilancia", "/mi-watchlist"],
      ["Abre tu primer pursuit", "/radar"],
    ]) {
      expect(screen.getByText(titulo).closest("a")?.getAttribute("href")).toBe(destino);
    }
  });

  it("dice qué gana el usuario, no «bienvenido a TenderFlow»", async () => {
    renderBanda();
    await screen.findByRole("heading", { name: "Primeros pasos" });
    expect(screen.getByText(/el Radar puntúa con pesos genéricos/)).toBeInTheDocument();
    expect(screen.queryByText(/bienvenid/i)).not.toBeInTheDocument();
  });

  it("el paso ya hecho no se pide otra vez", async () => {
    backend.perfil = PERFIL_HECHO;
    renderBanda();
    await esperarResuelto(1);

    const fila = filaDe("Ajusta tu perfil de scoring");
    expect(within(fila).getByText("hecho")).toBeInTheDocument();
    expect(within(fila).queryByRole("link")).toBeNull();
  });

  it("con todo configurado no se muestra nada", async () => {
    // Control primero: con la cuenta vacía la banda SÍ sale, así que la
    // ausencia de abajo no puede ser un falso verde del montaje.
    renderBanda();
    await screen.findByRole("heading", { name: "Primeros pasos" });
    cleanup();

    backend.perfil = PERFIL_HECHO;
    backend.reglas = REGLA_ACTIVA;
    backend.pursuits = { items: [], total: 4, limit: 50, offset: 0, organization_id: 1 };
    apiGet.mockClear();

    renderBanda();
    await waitFor(() => expect(rutasPedidas()).toContain("/api/v1/pursuits"));
    await noApareceLaBanda();
  });

  it("una regla desactivada no cuenta como regla creada", async () => {
    backend.reglas = {
      items: [{ id: 1, active: false, email: null, frequency: "daily", match_count: 0 }],
    };
    renderBanda();
    await esperarResuelto(0);
    // No vigila nada: el usuario no recibiría ni una señal por ella.
    expect(within(filaDe("Crea una regla de vigilancia")).getByText("pendiente")).toBeInTheDocument();
  });

  it("mientras una query carga no afirma que el paso esté pendiente", async () => {
    backend.cuelgan = new Set(["/api/v1/watchlist/rules"]);
    renderBanda();
    // El perfil sí está acreditadamente pendiente, así que la banda se enciende.
    await screen.findByText("0 de 3 hechos · 1 sin comprobar");

    const fila = filaDe("Crea una regla de vigilancia");
    expect(within(fila).getByText("comprobando")).toBeInTheDocument();
    expect(within(fila).queryByText("pendiente")).toBeNull();
    // Y su fila no es un enlace: no se le pide algo que quizá ya tenga hecho.
    expect(within(fila).queryByRole("link")).toBeNull();
  });

  it("no se enciende cuando todavía no se sabe nada de ningún paso", async () => {
    backend.cuelgan = new Set([
      "/api/v1/me/profile",
      "/api/v1/watchlist/rules",
      "/api/v1/pursuits",
    ]);
    renderBanda();
    await waitFor(() => expect(rutasPedidas()).toContain("/api/v1/pursuits"));
    await noApareceLaBanda();
  });

  it("una query rota se declara sin comprobar en vez de darse por pendiente", async () => {
    backend.fallan = new Set(["/api/v1/watchlist/rules"]);
    renderBanda();
    await screen.findByText("0 de 3 hechos · 1 sin comprobar");

    const fila = filaDe("Crea una regla de vigilancia");
    expect(within(fila).getByText("sin comprobar")).toBeInTheDocument();
    expect(within(fila).queryByRole("link")).toBeNull();
  });

  it("«Ocultar» retira la banda, lo recuerda y devuelve el foco", async () => {
    const onDescartar = vi.fn();
    renderBanda({ onDescartar });
    await screen.findByRole("heading", { name: "Primeros pasos" });

    fireEvent.click(screen.getByRole("button", { name: "Ocultar los primeros pasos" }));

    expect(screen.queryByRole("heading", { name: "Primeros pasos" })).not.toBeInTheDocument();
    expect(estaDescartado()).toBe(true);
    expect(onDescartar).toHaveBeenCalledTimes(1);
  });

  /**
   * «Ocultar» es la señal de rechazo del onboarding, y sin medirla una caída
   * del embudo no se distingue de un abandono silencioso. Lo que se fija aquí
   * es que el evento salga **y** que sólo lleve la categoría de progreso: por
   * ahí no puede colarse nada del usuario.
   */
  it("«Ocultar» emite el rechazo con el progreso en que se descartó", async () => {
    renderBanda();
    await esperarResuelto(0);

    fireEvent.click(screen.getByRole("button", { name: "Ocultar los primeros pasos" }));

    expect(eventos).toHaveBeenCalledWith("onboarding_ocultado", { progreso: "0" });
  });

  it("distingue el rechazo de entrada del abandono con trabajo hecho", async () => {
    backend.perfil = PERFIL_HECHO;
    renderBanda();
    await esperarResuelto(1);

    fireEvent.click(screen.getByRole("button", { name: "Ocultar los primeros pasos" }));

    expect(eventos).toHaveBeenCalledWith("onboarding_ocultado", { progreso: "1" });
  });

  it("descartada en este dispositivo, no vuelve ni pide los datos", async () => {
    window.localStorage.setItem("lsap:v1:onboarding-primeros-pasos-oculto", "true");
    renderBanda();
    await waitFor(() => expect(rutasPedidas()).toContain("/api/v1/organizations"));
    await noApareceLaBanda();

    // Un veterano no paga tres peticiones para no ver nada; `/organizations` la
    // pide el resto de la pantalla igualmente.
    expect(rutasPedidas()).not.toContain("/api/v1/me/profile");
    expect(rutasPedidas()).not.toContain("/api/v1/watchlist/rules");
    expect(rutasPedidas()).not.toContain("/api/v1/pursuits");
  });
});
