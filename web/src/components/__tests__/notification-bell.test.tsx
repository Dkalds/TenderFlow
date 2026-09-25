import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMutate = vi.fn().mockResolvedValue({});
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
  apiMutate: (...a: unknown[]) => apiMutate(...a),
}));
vi.mock("@/lib/report-error", () => ({ reportError: vi.fn() }));

// jsdom has no EventSource — provide a controllable stub.
type Listener = (event: { data: string }) => void;
class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, Listener> = {};
  cerrado = false;
  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: Listener) {
    this.listeners[type] = cb;
  }
  close() {
    this.cerrado = true;
  }
}

import { MARGEN_OCULTA_MS, NotificationBell } from "@/components/notification-bell";

// Radix's DropdownMenu trigger opens on pointer down (not on a synthetic
// `click`) and only mounts its content in the DOM while open.
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
}

function renderBell(
  data?: unknown,
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }),
) {
  if (data !== undefined) qc.setQueryData(["notifications"], data);
  return render(
    <QueryClientProvider client={qc}>
      <NotificationBell />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
});
afterEach(() => {
  vi.unstubAllGlobals();
  apiMutate.mockClear();
});

describe("NotificationBell", () => {
  it("shows an empty state and 'no live connection' before SSE opens", () => {
    renderBell({ items: [], unread_count: 0, hoy: { calientes: 0, vencen_48h: 0, nuevas_24h: 0, total_activas: 0 } });
    openMenu(screen.getByRole("button", { name: /Notificaciones/ }));
    expect(screen.getByText("Sin notificaciones")).toBeInTheDocument();
    expect(screen.getByText("Sin conexión en vivo")).toBeInTheDocument();
  });

  it("renders notification items, hoy counters and an unread badge", () => {
    renderBell({
      items: [
        { id: "L1", titulo: "Licitación caliente", importe: 100, organo_contratacion: "Ayto", read: false },
        { id: "L2", titulo: null, importe: null, organo_contratacion: null, read: true },
      ],
      unread_count: 3,
      hoy: { calientes: 2, vencen_48h: 1, nuevas_24h: 4, total_activas: 10 },
    });
    // Unread badge in the trigger aria-label (present even before opening).
    const trigger = screen.getByRole("button", { name: /3 sin leer/ });
    openMenu(trigger);
    expect(screen.getByText("Licitación caliente")).toBeInTheDocument();
    expect(screen.getByText("Nuevas 24h")).toBeInTheDocument();
  });

  it("marks all as read when the bell is clicked", async () => {
    renderBell({
      items: [{ id: "L1", titulo: "X", importe: null, organo_contratacion: null, read: false }],
      unread_count: 1,
      hoy: { calientes: 0, vencen_48h: 0, nuevas_24h: 0, total_activas: 0 },
    });
    fireEvent.click(screen.getByRole("button", { name: /Notificaciones/ }));
    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/notifications/read", { ids: ["L1"] }),
    );
  });

  it("F5.6: una alerta sobre un expediente se puede silenciar o posponer desde la campana", async () => {
    const alerta = {
      id: 5,
      created_at: null,
      type: "rule_match",
      title: "SAP en Madrid",
      body: null,
      licitacion_id: "LIC-9",
      rule_id: 3,
      pursuit_id: null,
      read: true,
    };
    renderBell({
      items: [],
      unread_count: 0,
      alerts: [alerta, { ...alerta, id: 6, title: "Sin expediente", licitacion_id: null }],
      alerts_unread_count: 0,
      hoy: { calientes: 0, vencen_48h: 0, nuevas_24h: 0, total_activas: 0 },
    });
    openMenu(screen.getByRole("button", { name: /Notificaciones/ }));

    // Sin expediente no hay nada que silenciar: sólo una pareja de acciones.
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

    openMenu(screen.getByRole("button", { name: /Notificaciones/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Recordármelo en 7 días: SAP en Madrid" }));
    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith(
        "POST",
        "/api/v1/radar/dismissals",
        expect.objectContaining({ accion: "posponer", dias: 7 }),
      ),
    );
  });

  it("surfaces a live SSE item and clears the 'no connection' notice", () => {
    renderBell({ items: [], unread_count: 0, hoy: { calientes: 0, vencen_48h: 0, nuevas_24h: 0, total_activas: 0 } });
    const es = MockEventSource.instances[0];
    act(() => es.onopen?.());
    act(() =>
      es.listeners["licitaciones_nuevas"]?.({ data: JSON.stringify({ message: "5 nuevas licitaciones" }) }),
    );
    openMenu(screen.getByRole("button", { name: /Notificaciones/ }));
    expect(screen.getByText("5 nuevas licitaciones")).toBeInTheDocument();
    expect(screen.queryByText("Sin conexión en vivo")).not.toBeInTheDocument();
  });
});

/*
 * Pestaña oculta: cada SSE abierto ocupa una de las 20 plazas de concurrencia
 * de uvicorn en la API, también el de una pestaña olvidada en segundo plano.
 * Se cierra tras un margen y se reabre al volver, pidiendo otra vez el feed.
 */
describe("NotificationBell — SSE con la pestaña oculta", () => {
  let visibilidad: DocumentVisibilityState = "visible";
  const VACIO = { items: [], unread_count: 0, hoy: { calientes: 0, vencen_48h: 0, nuevas_24h: 0, total_activas: 0 } };

  function cambiarVisibilidad(estado: DocumentVisibilityState) {
    visibilidad = estado;
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
  }

  const avanzar = (ms: number) =>
    act(() => {
      vi.advanceTimersByTime(ms);
    });

  beforeEach(() => {
    visibilidad = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibilidad });
    // Solo los temporizadores de la campana (margen y backoff); el resto del
    // árbol sigue con los reales.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  });

  afterEach(() => {
    vi.useRealTimers();
    // Vuelve a la propiedad de jsdom (la del prototipo).
    delete (document as { visibilityState?: unknown }).visibilityState;
  });

  it("no cierra por un cambio rápido de pestaña: el margen se reinicia al volver", () => {
    renderBell(VACIO);
    const es = MockEventSource.instances[0];

    cambiarVisibilidad("hidden");
    avanzar(MARGEN_OCULTA_MS - 1);
    cambiarVisibilidad("visible");
    avanzar(MARGEN_OCULTA_MS);

    expect(es.cerrado).toBe(false);
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it("cierra el SSE tras el margen oculta y, al volver, reconecta y vuelve a pedir el feed", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const invalidar = vi.spyOn(qc, "invalidateQueries");
    renderBell(VACIO, qc);
    const primera = MockEventSource.instances[0];
    act(() => primera.onopen?.());

    cambiarVisibilidad("hidden");
    avanzar(MARGEN_OCULTA_MS);

    expect(primera.cerrado).toBe(true);
    // Oculta no reintenta: la plaza queda libre hasta que se vuelva.
    avanzar(10 * MARGEN_OCULTA_MS);
    expect(MockEventSource.instances).toHaveLength(1);
    expect(invalidar).not.toHaveBeenCalled();

    cambiarVisibilidad("visible");

    expect(MockEventSource.instances).toHaveLength(2);
    // Sin cancelar el refresco al volver que ya pueda estar en vuelo.
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ["notifications"] }, { cancelRefetch: false });
    openMenu(screen.getByRole("button", { name: /Notificaciones/ }));
    // Reconectando: hasta que abre, no se finge conexión en vivo.
    expect(screen.getByText("Sin conexión en vivo")).toBeInTheDocument();
  });

  it("volver a la pestaña no reinicia el backoff de una API que estaba fallando", () => {
    renderBell(VACIO);
    // Primer fallo: se reintenta al segundo y el siguiente fallo esperará 2 s.
    act(() => MockEventSource.instances[0].onerror?.());
    avanzar(1_000);
    expect(MockEventSource.instances).toHaveLength(2);

    cambiarVisibilidad("hidden");
    avanzar(MARGEN_OCULTA_MS);
    cambiarVisibilidad("visible");
    // Al volver se conecta en el acto…
    expect(MockEventSource.instances).toHaveLength(3);

    // …pero si vuelve a fallar, espera lo que tocaba (2 s), no el segundo inicial.
    act(() => MockEventSource.instances[2].onerror?.());
    avanzar(1_999);
    expect(MockEventSource.instances).toHaveLength(3);
    avanzar(1);
    expect(MockEventSource.instances).toHaveLength(4);
  });

  it("una pestaña abierta en segundo plano no conecta hasta que se mira", () => {
    visibilidad = "hidden";
    renderBell(VACIO);
    expect(MockEventSource.instances).toHaveLength(0);

    cambiarVisibilidad("visible");
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it("al desmontarse cierra el SSE y deja de escuchar la visibilidad", () => {
    const { unmount } = renderBell(VACIO);
    const es = MockEventSource.instances[0];

    unmount();
    cambiarVisibilidad("hidden");
    cambiarVisibilidad("visible");

    expect(es.cerrado).toBe(true);
    expect(MockEventSource.instances).toHaveLength(1);
  });
});
