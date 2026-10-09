import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Ops no afirma lo que no ha leído (ADR-014).
 *
 * Cada caso es una lectura que, al fallar, se pintaba como su contrario: el
 * historial de entregas caído como «sin entregas» y las concesiones sin leer
 * como «no hay concesiones». Ahora el fallo se dice como fallo, con su
 * «Reintentar».
 *
 * La misma regla para la cola de errores sin medir («—», no «0») está en
 * `health-strip.test.tsx`, que es donde vive ese recuento desde 2026-10; la de
 * la lista de claves se fue con su tarjeta (la que funciona está en Ajustes).
 */

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

describe("DeliveriesPanel", () => {
  it("con el historial caído dice que falló, no «sin entregas»", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    conConsultas(<DeliveriesPanel webhookId={3} />);

    expect(await screen.findByText("No se pudo cargar el historial de entregas")).toBeInTheDocument();
    expect(screen.queryByText(/Sin entregas/)).not.toBeInTheDocument();
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
