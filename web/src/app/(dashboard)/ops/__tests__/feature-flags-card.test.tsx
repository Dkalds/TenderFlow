import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Feature flags: se guarda lo que cambió, y se sabe si hay algo por guardar.
 *
 * El botón «Guardar cambios» estaba siempre activo, no confirmaba el guardado y
 * enviaba **todas** las flags: pisaba el cambio que otro administrador hubiera
 * hecho entretanto y dejaba un evento de auditoría por cada flag que nadie
 * había tocado.
 */

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastMock }));

import { FeatureFlagsCard } from "../_components/administracion/feature-flags-card";

const FLAGS = [
  { flag: "mercado_clusters", enabled: true, rollout_pct: 100, description: "Clusters", updated_at: null },
  { flag: "radar_nuevo", enabled: false, rollout_pct: 0, description: "Radar", updated_at: null },
];

function montar(flags: unknown = FLAGS, status = 200) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    if (callMethod(call) === "PUT") return Promise.resolve(jsonResponse({ status: "ok" }));
    return Promise.resolve(jsonResponse(flags, status));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <FeatureFlagsCard />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

const guardar = () => screen.getByRole("button", { name: "Guardar cambios" });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("FeatureFlagsCard", () => {
  it("sin cambios no hay nada que guardar", async () => {
    montar();

    await screen.findByText("mercado_clusters");
    expect(guardar()).toBeDisabled();
    expect(screen.queryByText(/sin guardar/)).not.toBeInTheDocument();
  });

  it("guarda solo la flag que cambió y lo confirma", async () => {
    const fetchMock = montar();

    fireEvent.click(await screen.findByRole("switch", { name: "Activar radar_nuevo" }));
    expect(screen.getByText("1 cambio sin guardar")).toBeInTheDocument();
    fireEvent.click(guardar());

    await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("Cambios guardados"));
    const put = fetchMock.mock.calls.find((c) => callMethod(c) === "PUT");
    expect(put && callUrl(put)).toBe("/api/v1/feature-flags");
    expect(JSON.parse(String((put?.[1] as RequestInit).body))).toEqual({
      // Al encenderla sin tocar el despliegue, va entera: una flag activa al
      // 0 % no enciende nada.
      flags: [{ flag: "radar_nuevo", enabled: true, rollout_pct: 100 }],
    });
  });

  it("volver al valor original deja de contar como cambio", async () => {
    montar();
    const interruptor = await screen.findByRole("switch", { name: "Activar radar_nuevo" });

    fireEvent.click(interruptor);
    fireEvent.click(interruptor);

    expect(guardar()).toBeDisabled();
  });

  it("descartar devuelve las flags a lo que dice el servidor", async () => {
    const fetchMock = montar();

    fireEvent.click(await screen.findByRole("switch", { name: "Activar mercado_clusters" }));
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));

    expect(screen.getByRole("switch", { name: "Activar mercado_clusters" })).toBeChecked();
    expect(guardar()).toBeDisabled();
    expect(fetchMock.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(false);
  });

  it("con la lectura caída dice que falló, no que no hay flags", async () => {
    montar({ detail: "boom" }, 500);

    expect(await screen.findByText("No se pudieron cargar los feature flags")).toBeInTheDocument();
    expect(screen.queryByText("No hay feature flags definidos")).not.toBeInTheDocument();
  });

  it("sin flags lo dice y no ofrece guardar", async () => {
    montar([]);

    expect(await screen.findByText("No hay feature flags definidos")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar cambios" })).not.toBeInTheDocument();
  });
});
