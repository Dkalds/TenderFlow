import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * CU-34. La banda de primeros pasos sólo vale si se apaga sola. Lo que estos tests
 * fijan no es el marcado: es que el estado venga del servidor y que ningún
 * estado intermedio se lea como una carencia del usuario.
 *
 * Se dobla el cliente tipado entero y se responde por ruta, que es como se
 * comporta de verdad: así el test ejercita también el gateo por `organizations`
 * y las tres señales a la vez. La capacidad y los NIFs van por `fetchWithAuth`
 * (ruta con id), las demás por `apiGet`; los dos dobles comparten respuestas.
 */

interface RespuestasFalsas {
  capacidad: unknown;
  nifs: unknown;
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
      capacidad: {
        organization_id: 1,
        campos_incompletos: ["certificaciones", "facturacion", "referencias", "perfiles_equipo"],
      },
      nifs: { organization_id: 1, nifs: [] },
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
    if (path === "/api/v1/organizations/1/capabilities") return Promise.resolve(backend.capacidad);
    if (path === "/api/v1/organizations/1/nifs") return Promise.resolve(backend.nifs);
    if (path === "/api/v1/watchlist/rules") return Promise.resolve(backend.reglas);
    if (path === "/api/v1/pursuits") return Promise.resolve(backend.pursuits);
    if (path === "/api/v1/organizations") return Promise.resolve(backend.organizations);
    return Promise.reject(new Error(`ruta no doblada: ${path}`));
  }),
);

vi.mock("@/lib/api-client", () => ({
  apiGet,
  apiMutate: vi.fn(),
  // La misma tabla de rutas: lo que distingue a los dos es solo si la ruta
  // lleva un id.
  fetchWithAuth: apiGet,
}));

vi.mock("@/lib/analytics", () => ({
  primeraVez: () => false,
  registrarEvento: vi.fn(),
}));

import { PrimerosPasos } from "@/app/(dashboard)/resumen/_components/primeros-pasos";
import { estaDescartado } from "@/components/onboarding/descarte";
import { registrarEvento } from "@/lib/analytics";

const eventos = vi.mocked(registrarEvento);

const CAPACIDAD_COMPLETA = {
  organization_id: 1,
  // Referencias y perfiles de equipo no los exige el paso.
  campos_incompletos: ["referencias", "perfiles_equipo"],
};
const UN_NIF = {
  organization_id: 1,
  nifs: [{ id: 1, nif: "B12345678", razon_social: "Acme", principal: true, created_at: "2026-10-01T00:00:00Z" }],
};
const REGLA_ACTIVA = {
  items: [{ id: 1, active: true, email: null, frequency: "daily", match_count: 3 }],
};
const CAPACIDAD = "Completa la capacidad de tu organización";
const ALERTA = "Revisa tu alerta";
const OPORTUNIDAD = "Abre tu primera oportunidad";

function renderBanda(
  props: { onDescartar?: () => void; posicion?: "arriba" | "abajo" } = {},
) {
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

/** La cuenta recién creada: nada declarado, nada abierto. */
function cuentaNueva() {
  backend.capacidad = {
    organization_id: 1,
    campos_incompletos: ["certificaciones", "facturacion", "referencias", "perfiles_equipo"],
  };
  backend.nifs = { organization_id: 1, nifs: [] };
  backend.reglas = { items: [] };
  backend.pursuits = { items: [], total: 0, limit: 50, offset: 0, organization_id: 1 };
  backend.organizations = [{ id: 1, name: "Acme", role: "owner" }];
  backend.fallan = new Set();
  backend.cuelgan = new Set();
}

describe("PrimerosPasos", () => {
  beforeEach(() => {
    cleanup();
    window.localStorage.clear();
    apiGet.mockClear();
    eventos.mockClear();
    cuentaNueva();
  });

  it("con una cuenta recién creada saca los tres pasos y adónde va cada uno", async () => {
    renderBanda();
    expect(await screen.findByRole("heading", { name: "Primeros pasos" })).toBeInTheDocument();
    await esperarResuelto(0);

    for (const [titulo, destino] of [
      [CAPACIDAD, "/equipo?tab=organizacion"],
      [ALERTA, "/mi-watchlist"],
      [OPORTUNIDAD, "/radar"],
    ]) {
      expect(screen.getByText(titulo).closest("a")?.getAttribute("href")).toBe(destino);
    }
  });

  it("dice qué gana el usuario, no «bienvenido a TenderFlow»", async () => {
    renderBanda();
    await screen.findByRole("heading", { name: "Primeros pasos" });
    expect(screen.getByText(/el checklist de cada pliego contesta «desconocido»/)).toBeInTheDocument();
    expect(screen.queryByText(/bienvenid/i)).not.toBeInTheDocument();
  });

  it("la capacidad está hecha con certificaciones, facturación y un NIF", async () => {
    backend.capacidad = CAPACIDAD_COMPLETA;
    backend.nifs = UN_NIF;
    renderBanda();
    await esperarResuelto(1);

    const fila = filaDe(CAPACIDAD);
    expect(within(fila).getByText("hecho")).toBeInTheDocument();
    expect(within(fila).queryByRole("link")).toBeNull();
  });

  it("sin NIF la capacidad sigue pendiente aunque el perfil esté completo", async () => {
    backend.capacidad = CAPACIDAD_COMPLETA;
    renderBanda();
    await esperarResuelto(0);
    expect(within(filaDe(CAPACIDAD)).getByText("pendiente")).toBeInTheDocument();
  });

  it("con NIF pero sin facturación, también pendiente", async () => {
    backend.capacidad = { organization_id: 1, campos_incompletos: ["facturacion"] };
    backend.nifs = UN_NIF;
    renderBanda();
    await esperarResuelto(0);
    expect(within(filaDe(CAPACIDAD)).getByText("pendiente")).toBeInTheDocument();
  });

  it("a quien no gestiona la organización no le pide los NIFs ni le da la capacidad por hecha", async () => {
    // La API solo sirve los NIFs a owner y admin: pedirlos como `member` es un
    // 403 seguro, y sin ellos no se sabe si el paso está hecho.
    backend.organizations = [{ id: 1, name: "Acme", role: "member" }];
    backend.capacidad = CAPACIDAD_COMPLETA;
    renderBanda();
    await screen.findByText("0 de 3 hechos · 1 sin comprobar");

    expect(within(filaDe(CAPACIDAD)).getByText("sin comprobar")).toBeInTheDocument();
    expect(rutasPedidas()).not.toContain("/api/v1/organizations/1/nifs");
  });

  it("a quien no gestiona sí le dice lo que falta del perfil, que puede leer", async () => {
    backend.organizations = [{ id: 1, name: "Acme", role: "member" }];
    renderBanda();
    await esperarResuelto(0);
    expect(within(filaDe(CAPACIDAD)).getByText("pendiente")).toBeInTheDocument();
  });

  it("con todo hecho no se muestra nada", async () => {
    // Control primero: con la cuenta vacía la banda SÍ sale, así que la
    // ausencia de abajo no puede ser un falso verde del montaje.
    renderBanda();
    await screen.findByRole("heading", { name: "Primeros pasos" });
    cleanup();

    backend.capacidad = CAPACIDAD_COMPLETA;
    backend.nifs = UN_NIF;
    backend.reglas = REGLA_ACTIVA;
    backend.pursuits = { items: [], total: 4, limit: 50, offset: 0, organization_id: 1 };
    apiGet.mockClear();

    renderBanda();
    await waitFor(() => expect(rutasPedidas()).toContain("/api/v1/pursuits"));
    await noApareceLaBanda();
  });

  it("revisar la alerta es tenerla: una pausada también cuenta", async () => {
    backend.reglas = {
      items: [{ id: 1, active: false, email: null, frequency: "daily", match_count: 0 }],
    };
    renderBanda();
    await esperarResuelto(1);
    expect(within(filaDe(ALERTA)).getByText("hecho")).toBeInTheDocument();
  });

  it("con una oportunidad abierta, ese paso está hecho", async () => {
    backend.pursuits = { items: [], total: 1, limit: 50, offset: 0, organization_id: 1 };
    renderBanda();
    await esperarResuelto(1);
    expect(within(filaDe(OPORTUNIDAD)).getByText("hecho")).toBeInTheDocument();
  });

  it("mientras una query carga no afirma que el paso esté pendiente", async () => {
    backend.cuelgan = new Set(["/api/v1/watchlist/rules"]);
    renderBanda();
    // La capacidad sí está acreditadamente pendiente, así que la banda se enciende.
    await screen.findByText("0 de 3 hechos · 1 sin comprobar");

    const fila = filaDe(ALERTA);
    expect(within(fila).getByText("comprobando")).toBeInTheDocument();
    expect(within(fila).queryByText("pendiente")).toBeNull();
    // Y su fila no es un enlace: no se le pide algo que quizá ya tenga hecho.
    expect(within(fila).queryByRole("link")).toBeNull();
  });

  it("no se enciende cuando todavía no se sabe nada de ningún paso", async () => {
    backend.cuelgan = new Set([
      "/api/v1/organizations/1/capabilities",
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

    const fila = filaDe(ALERTA);
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
    backend.reglas = REGLA_ACTIVA;
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

    // Un veterano no paga peticiones para no ver nada; `/organizations` la
    // pide el resto de la pantalla igualmente.
    expect(rutasPedidas()).not.toContain("/api/v1/organizations/1/capabilities");
    expect(rutasPedidas()).not.toContain("/api/v1/organizations/1/nifs");
    expect(rutasPedidas()).not.toContain("/api/v1/watchlist/rules");
    expect(rutasPedidas()).not.toContain("/api/v1/pursuits");
  });
});

/**
 * Dónde va la banda. La vista monta una instancia en cada hueco —arriba del
 * todo y debajo de «Tu día»— y solo se pinta la que toca: arriba en una cuenta
 * sin ningún paso hecho, abajo en cuanto hay uno. Con algo sin comprobar no
 * sube: sería afirmar una cuenta vacía que puede no serlo.
 */
describe("PrimerosPasos · posición", () => {
  beforeEach(() => {
    cleanup();
    window.localStorage.clear();
    apiGet.mockClear();
    cuentaNueva();
  });

  it("en una cuenta recién creada sube arriba", async () => {
    renderBanda({ posicion: "arriba" });
    expect(await screen.findByRole("heading", { name: "Primeros pasos" })).toBeInTheDocument();
    await esperarResuelto(0);
  });

  it("en una cuenta recién creada no se repite abajo", async () => {
    renderBanda({ posicion: "abajo" });
    await noApareceLaBanda();
  });

  it("con un paso hecho vuelve debajo de «Tu día»", async () => {
    backend.reglas = REGLA_ACTIVA;
    renderBanda({ posicion: "abajo" });
    await esperarResuelto(1);
    cleanup();

    renderBanda({ posicion: "arriba" });
    await noApareceLaBanda();
  });

  it("con un paso sin comprobar no sube", async () => {
    backend.fallan = new Set(["/api/v1/watchlist/rules"]);
    renderBanda({ posicion: "arriba" });
    await noApareceLaBanda();
    cleanup();

    renderBanda({ posicion: "abajo" });
    expect(await screen.findByRole("heading", { name: "Primeros pasos" })).toBeInTheDocument();
  });
});
