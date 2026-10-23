/**
 * Ficha de webhook: rotar el secreto y reenviar una entrega fallida (CU-31).
 *
 * Con los hooks reales y `fetch` doblado: lo que importa es la petición que
 * sale (ruta y organización) y lo que se enseña con la respuesta. Las reglas
 * de autorización están en `tests/test_webhooks_redeliver.py` y
 * `tests/test_webhooks_rotate_secret.py`.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));

import { toast } from "sonner";
import { WebhookRow } from "../webhook-row";
import type { WebhookAmpliado } from "../../../_hooks/use-webhooks-ambito";

const WEBHOOK: WebhookAmpliado = {
  id: 5,
  name: "Slack del equipo",
  url: "https://hooks.example.test/x",
  event_types: ["pursuit.*"],
  active: true,
  organization_id: 12,
  formato: "slack_blocks",
  failure_count: 0,
} as WebhookAmpliado;

type Respuesta = { status: number; body: unknown };
let respuestas: Record<string, Respuesta>;
const fetchMock = vi.fn();

function metodo(init?: RequestInit): string {
  return init?.method ?? "GET";
}

function llamadas(m: string, ruta: string) {
  return fetchMock.mock.calls.filter(([url, init]) => metodo(init as RequestInit) === m && String(url) === ruta);
}

function pintar(webhook: WebhookAmpliado = WEBHOOK, editable = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <WebhookRow webhook={webhook} editable={editable} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  respuestas = {
    "POST /api/v1/webhooks/5/rotate-secret?organization_id=12": {
      status: 200,
      body: { id: 5, secret: "whsec_nuevo", rotated_at: "2026-10-23T10:00:00+00:00" }, // pragma: allowlist secret
    },
    "GET /api/v1/webhooks/5/deliveries?organization_id=12": {
      status: 200,
      body: [
        { id: 31, webhook_id: 5, event_type: "pursuit.updated", status_code: 500, success: false, created_at: "2026-10-22T09:00:00", estado: "failed" },
        { id: 32, webhook_id: 5, event_type: "pursuit.created", status_code: 503, success: false, created_at: "2026-10-22T10:00:00", estado: "pending" },
        { id: 33, webhook_id: 5, event_type: "ping", status_code: 0, success: false, created_at: "2026-10-22T11:00:00", estado: null },
        { id: 34, webhook_id: 5, event_type: "pursuit.won", status_code: 200, success: true, created_at: "2026-10-22T12:00:00", estado: "delivered" },
      ],
    },
    "POST /api/v1/webhooks/5/deliveries/31/redeliver?organization_id=12": { status: 202, body: { status: "encolada" } },
  };
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const r = respuestas[`${metodo(init)} ${url}`] ?? { status: 404, body: { detail: "no" } };
    return Promise.resolve(
      new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("WebhookRow: rotar el secreto", () => {
  it("pide confirmación, rota en la organización del webhook y enseña el secreto una vez", async () => {
    pintar();
    fireEvent.click(screen.getByRole("button", { name: "Rotar el secreto de Slack del equipo" }));

    const confirmacion = screen.getByRole("group", { name: /Confirmar la rotación/ });
    expect(within(confirmacion).getByText(/deja de firmar en el acto/)).toBeInTheDocument();
    // Lo seguro con el teclado: el foco cae en «Cancelar».
    expect(within(confirmacion).getByRole("button", { name: "Cancelar" })).toHaveFocus();
    expect(llamadas("POST", "/api/v1/webhooks/5/rotate-secret?organization_id=12")).toHaveLength(0);

    fireEvent.click(within(confirmacion).getByRole("button", { name: "Sí, rotar" }));

    expect(await screen.findByText("whsec_nuevo")).toBeInTheDocument();
    expect(llamadas("POST", "/api/v1/webhooks/5/rotate-secret?organization_id=12")).toHaveLength(1);
    expect(screen.getByText(/El secreto anterior ya no firma/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Confirmar la rotación/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ya lo he guardado" }));
    expect(screen.queryByText("whsec_nuevo")).not.toBeInTheDocument();
  });

  it("cancelar no rota nada", () => {
    pintar();
    fireEvent.click(screen.getByRole("button", { name: "Rotar el secreto de Slack del equipo" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Rotar el secreto de Slack del equipo" })).toHaveFocus();
  });

  it("la vista global, de solo lectura, no ofrece rotar", () => {
    pintar(WEBHOOK, false);
    expect(screen.queryByRole("button", { name: /Rotar el secreto/ })).not.toBeInTheDocument();
  });
});

describe("WebhookRow: reenviar una entrega", () => {
  it("solo las fallidas se reenvían, y la petición va a su webhook y su organización", async () => {
    pintar();
    fireEvent.click(screen.getByRole("button", { name: "Ver entregas" }));

    const botones = await screen.findAllByRole("button", { name: /Reenviar la entrega/ });
    // La `pending` ya está en cola, el ping no guarda cuerpo y la entregada no falló.
    expect(botones).toHaveLength(1);
    expect(screen.getByText("En cola · 503")).toBeInTheDocument();

    fireEvent.click(botones[0]);

    await waitFor(() =>
      expect(llamadas("POST", "/api/v1/webhooks/5/deliveries/31/redeliver?organization_id=12")).toHaveLength(1),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/en cola/i)));
    // El historial se vuelve a pedir para que la fila diga que está en cola.
    await waitFor(() =>
      expect(llamadas("GET", "/api/v1/webhooks/5/deliveries?organization_id=12").length).toBeGreaterThan(1),
    );
  });

  it("un 409 dice que esa entrega ya no se puede reenviar", async () => {
    respuestas["POST /api/v1/webhooks/5/deliveries/31/redeliver?organization_id=12"] = {
      status: 409,
      body: { detail: "La entrega ya se completó." },
    };
    pintar();
    fireEvent.click(screen.getByRole("button", { name: "Ver entregas" }));
    fireEvent.click(await screen.findByRole("button", { name: /Reenviar la entrega/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Esa entrega ya se completó o no se puede reenviar"),
    );
  });

  it("la vista global enseña el historial sin el botón de reenviar", async () => {
    pintar(WEBHOOK, false);
    fireEvent.click(screen.getByRole("button", { name: "Ver entregas" }));

    expect(await screen.findByText("pursuit.updated")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();
  });
});
