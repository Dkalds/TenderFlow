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
  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: Listener) {
    this.listeners[type] = cb;
  }
  close() {}
}

import { NotificationBell } from "@/components/notification-bell";

// Radix's DropdownMenu trigger opens on pointer down (not on a synthetic
// `click`) and only mounts its content in the DOM while open.
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
}

function renderBell(data?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
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
