import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Ops no afirma lo que no ha leído (ADR-014).
 *
 * Cada caso es una lectura que, al fallar, se pintaba como su contrario: la
 * lista de claves caída salía como «no hay claves», el historial de entregas
 * caído como «sin entregas», la cola sin medir como «0 registros» y las
 * concesiones sin leer como «no hay concesiones». Ahora el fallo se dice como
 * fallo, con su «Reintentar».
 */

import { ApiKeysCard } from "../_components/administracion/api-keys-card";
import { DlqPanel } from "../_components/observabilidad/dlq-panel";
import { AccesosDinamicos } from "../_components/solicitudes-acceso/accesos-dinamicos";
import { DeliveriesPanel } from "../_components/webhooks/deliveries-panel";

function conConsultas(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ApiKeysCard", () => {
  it("con la lectura caída dice que falló, no que no hay claves", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    conConsultas(<ApiKeysCard />);

    expect(await screen.findByText("No se pudieron cargar las claves")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reintentar/ })).toBeInTheDocument();
    expect(screen.queryByText("No hay claves de API registradas")).not.toBeInTheDocument();
  });

  it("no ofrece revocar una clave: la API no tiene esa operación", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ keys: [{ prefix: "tf_ab12", created_at: "2026-09-01T10:00:00Z", active: true }] }),
      ),
    );
    conConsultas(<ApiKeysCard />);

    expect(await screen.findByText("tf_ab12")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revocar/ })).not.toBeInTheDocument();
  });
});

describe("DeliveriesPanel", () => {
  it("con el historial caído dice que falló, no «sin entregas»", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    conConsultas(<DeliveriesPanel webhookId={3} />);

    expect(await screen.findByText("No se pudo cargar el historial de entregas")).toBeInTheDocument();
    expect(screen.queryByText(/Sin entregas/)).not.toBeInTheDocument();
  });
});

describe("DlqPanel", () => {
  it("sin recuento enseña una raya y lo dice, en vez de un 0", () => {
    render(<DlqPanel dlqCount={null} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText(/sin dato/)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("con cola, avisa y cuenta", () => {
    render(<DlqPanel dlqCount={4} />);

    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/Hay registros en la cola/);
  });
});

describe("AccesosDinamicos", () => {
  it("un fallo al leer no se confunde con «no hay concesiones»", () => {
    const onRetry = vi.fn();
    render(
      <AccesosDinamicos
        grants={undefined}
        isLoading={false}
        error={new Error("Failed to fetch")}
        onRetry={onRetry}
        revocando={false}
        onRevocar={() => {}}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("No se pudieron cargar los accesos concedidos");
    expect(screen.queryByText(/No hay concesiones dinámicas/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
