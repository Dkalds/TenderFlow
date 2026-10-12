import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/*
 * CU-29 — la campana enseña solo lo tuyo y marca como leído lo que abres.
 *
 * Hasta 2026-10-12 mezclaba contadores de mercado, licitaciones en vivo por
 * SSE y una lista de novedades siempre vacía, y marcaba todo como leído al
 * abrirse. Estos tests fijan lo contrario.
 */

type Query = Record<string, unknown>;

const { apiMutate, apiGet, fetchWithAuth, toast } = vi.hoisted(() => ({
  apiMutate: vi.fn().mockResolvedValue({}),
  apiGet: vi.fn(),
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
}));
vi.mock("@/lib/api-client", () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiMutate: (...a: unknown[]) => apiMutate(...a),
  fetchWithAuth: (...a: unknown[]) => fetchWithAuth(...(a as [])),
}));
vi.mock("@/lib/report-error", () => ({ reportError: vi.fn() }));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: (id: unknown) => id !== undefined,
}));
vi.mock("sonner", () => ({ toast }));
// «Ver todas» se carga bajo demanda con `next/dynamic`; aquí, el componente real.
vi.mock("next/dynamic", async () => {
  const { VerTodasSheet } = await import("@/components/campana/ver-todas-sheet");
  return { default: () => VerTodasSheet };
});

import { NotificationBell } from "@/components/notification-bell";

const REGLA_ALERTA = {
  id: 5,
  created_at: "2026-10-11T09:00:00+00:00",
  type: "watchlist_rule",
  title: "SAP en Madrid",
  body: null,
  licitacion_id: "LIC-9",
  rule_id: 3,
  pursuit_id: null,
  read: false,
};
const MENCION = {
  id: 6,
  created_at: "2026-10-10T09:00:00+00:00",
  type: "pursuit_mencion:44",
  title: "Te han mencionado en un comentario",
  body: null,
  licitacion_id: "LIC-2",
  rule_id: null,
  pursuit_id: 12,
  read: true,
};
const REGLA = {
  id: 3,
  nombre: "SAP",
  keyword: "SAP",
  cpv: null,
  min_importe: 50000,
  ccaa: "Madrid",
  frequency: "daily",
  active: true,
  tecnologia: null,
  organo: null,
  procedimiento: null,
  tipo_contrato: null,
  banda_min: null,
  plazo_min_dias: null,
  organization_id: 7,
  visibility: "private",
  match_count: 4,
  email: null,
};

function pagina(items: unknown[], extra: Partial<{ total: number; sin_leer: number }> = {}) {
  return {
    items,
    total: extra.total ?? items.length,
    sin_leer: extra.sin_leer ?? items.filter((a) => !(a as { read: boolean }).read).length,
    limit: 8,
    offset: 0,
  };
}

function backend(items: unknown[] = [REGLA_ALERTA, MENCION], extra = {}) {
  apiGet.mockImplementation(async (path: string, init?: { params?: { query?: Query } }) => {
    if (path === "/api/v1/notifications/alerts") return { ...pagina(items, extra), ...init?.params?.query };
    if (path === "/api/v1/watchlist/rules") return { items: [REGLA] };
    throw new Error(`ruta inesperada ${path}`);
  });
}

// El disparador de Radix abre con pointerdown (no con un `click` sintético) y
// solo monta el contenido mientras está abierto.
function abrirMenu() {
  const trigger = screen.getByRole("button", { name: /Notificaciones/ });
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
}

function renderBell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <NotificationBell />
    </QueryClientProvider>,
  );
}

class EventSourceEspia {
  static creados = 0;
  constructor() {
    EventSourceEspia.creados += 1;
  }
}

beforeEach(() => {
  EventSourceEspia.creados = 0;
  vi.stubGlobal("EventSource", EventSourceEspia as unknown as typeof EventSource);
});
afterEach(() => {
  vi.unstubAllGlobals();
  apiMutate.mockClear();
  apiGet.mockReset();
  toast.mockClear();
  toast.error.mockClear();
});

describe("NotificationBell — solo lo tuyo", () => {
  it("cuenta lo sin leer de la organización activa y abrirla no marca nada", async () => {
    backend();
    renderBell();

    expect(await screen.findByRole("button", { name: "Notificaciones (1 sin leer)" })).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith(
      "/api/v1/notifications/alerts",
      expect.objectContaining({
        params: { query: { organization_id: 7, estado: "todas", limit: 8, offset: 0 } },
      }),
    );

    abrirMenu();
    expect(screen.getByRole("menuitem", { name: /^SAP en Madrid/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Te han mencionado en un comentario" })).toHaveAttribute("href", "/oportunidades/12");
    expect(apiMutate).not.toHaveBeenCalled();
  });

  it("no pinta el mercado ni abre un SSE", async () => {
    backend();
    renderBell();
    abrirMenu();
    await screen.findByRole("menuitem", { name: /^SAP en Madrid/ });

    expect(screen.queryByText("Nuevas 24h")).not.toBeInTheDocument();
    expect(screen.queryByText("Sin conexión en vivo")).not.toBeInTheDocument();
    expect(EventSourceEspia.creados).toBe(0);
    expect(fetchWithAuth).not.toHaveBeenCalledWith("/api/v1/notifications", expect.anything());
  });

  it("abrir un aviso lo marca como leído a él solo", async () => {
    backend();
    renderBell();
    await screen.findByRole("button", { name: /1 sin leer/ });
    abrirMenu();

    fireEvent.click(screen.getByRole("menuitem", { name: /^SAP en Madrid/ }));

    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/notifications/alerts/read", {
        ids: [5],
        organization_id: 7,
      }),
    );
    expect(apiMutate).toHaveBeenCalledTimes(1);
  });

  it("«Marcar todo como leído» es una acción explícita", async () => {
    backend();
    renderBell();
    await screen.findByRole("button", { name: /1 sin leer/ });
    abrirMenu();

    fireEvent.click(screen.getByRole("menuitem", { name: "Marcar todo como leído" }));

    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/notifications/alerts/read", {
        all: true,
        organization_id: 7,
      }),
    );
  });

  it("sin nada pendiente no ofrece marcar y lo dice en lenguaje de usuario", async () => {
    backend([]);
    renderBell();
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    abrirMenu();

    expect(await screen.findByText(/Nada por ahora/)).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Marcar todo como leído" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Ver todas/ })).not.toBeInTheDocument();
  });

  it("F5.6: una alerta sobre un expediente se puede ocultar o posponer desde la campana", async () => {
    backend([REGLA_ALERTA, { ...REGLA_ALERTA, id: 8, title: "Sin expediente", licitacion_id: null, rule_id: null }]);
    renderBell();
    await screen.findByRole("button", { name: /sin leer/ });
    abrirMenu();

    // Sin expediente no hay nada que ocultar: sólo una pareja de acciones.
    expect(screen.getAllByRole("menuitem", { name: /Ocultar del Radar 30 días/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("menuitem", { name: "Ocultar del Radar 30 días: SAP en Madrid" }));
    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/radar/dismissals", {
        id_externo: "LIC-9",
        score: null,
        banda: null,
        accion: "silenciar",
        dias: 30,
      }),
    );
  });

  it("«Silenciar esta regla» la pone en pausa sin tocar sus criterios", async () => {
    backend();
    renderBell();
    await screen.findByRole("button", { name: /1 sin leer/ });
    abrirMenu();

    fireEvent.click(screen.getByRole("menuitem", { name: "Silenciar esta regla: SAP en Madrid" }));

    await waitFor(() => expect(apiMutate).toHaveBeenCalledWith("PUT", "/api/v1/watchlist/rules/3", expect.anything()));
    const [, , cuerpo] = apiMutate.mock.calls.find((c) => c[0] === "PUT")!;
    expect(cuerpo).toMatchObject({ active: false, keyword: "SAP", min_importe: 50000, ccaa: "Madrid" });
    expect(cuerpo).not.toHaveProperty("visibility");
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Regla en pausa: deja de avisarte", expect.anything()));
  });

  it("«Ver todas» abre la bandeja completa con filtro de lectura", async () => {
    backend([REGLA_ALERTA, MENCION], { total: 30, sin_leer: 1 });
    renderBell();
    await screen.findByRole("button", { name: /1 sin leer/ });
    abrirMenu();

    fireEvent.click(screen.getByRole("menuitem", { name: "Ver todas (30)" }));

    const panel = await screen.findByRole("dialog", { name: "Notificaciones" });
    await within(panel).findByText("1–20 de 30");
    fireEvent.click(within(panel).getByRole("button", { name: /Sin leer/ }));
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith(
        "/api/v1/notifications/alerts",
        expect.objectContaining({
          params: { query: { organization_id: 7, estado: "sin_leer", limit: 20, offset: 0 } },
        }),
      ),
    );
  });
});
