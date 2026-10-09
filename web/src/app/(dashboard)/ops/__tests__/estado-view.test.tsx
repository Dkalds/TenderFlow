import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * La vista Estado dice lo que la API dice, no lo que dice la red.
 *
 * `/api/v1/health` responde 200 también cuando está degradado. La cabecera
 * leía «hay respuesta» como «todo va bien»: con el esquema por detrás del
 * código seguía en verde, que es exactamente el incidente que esta pantalla
 * existe para enseñar.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

import ObservabilidadView from "../_components/observabilidad-view";

const SANO = {
  status: "ok",
  db: "ok",
  redis: "ok",
  disk: "ok",
  schema_revision: "ok (v146_lic_organo_norm_index)",
  timestamp: "2026-10-09T01:42:30+00:00",
};

const ERRORES = {
  items: [
    {
      fingerprint: "abc",
      origen: "window.onerror",
      ruta: "/radar",
      mensaje: "Cannot read properties of undefined",
      build: "b1",
      ocurrencias: 7,
      primera_vez: "2026-10-07T10:00:00+00:00",
      ultima_vez: "2026-10-08T10:00:00+00:00",
    },
  ],
};

function montar(health: unknown, { admin = false, status = 200 } = {}) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        jsonResponse({ user_id: "1", email: "a@b.es", display_name: "A", is_admin: admin }),
      );
    }
    if (url.startsWith("/api/v1/health")) return Promise.resolve(jsonResponse(health, status));
    if (url.startsWith("/api/v1/security/client-errors")) {
      return Promise.resolve(jsonResponse(ERRORES));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SessionProvider>
        <TooltipProvider>
          <ObservabilidadView />
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Ops › Estado", () => {
  it("con todo en orden lo dice una vez", async () => {
    montar(SANO);

    expect(await screen.findByText("En línea")).toBeInTheDocument();
    expect(screen.getByText("Todos los servicios responden")).toBeInTheDocument();
    // El semáforo de una línea repetía lo mismo debajo de la tira.
    expect(screen.queryByText("Sistema operativo")).not.toBeInTheDocument();
  });

  it("un degraded con HTTP 200 no se pinta como en línea", async () => {
    montar({ ...SANO, status: "degraded", redis: "degraded" });

    expect(await screen.findByText("Degradada")).toBeInTheDocument();
    expect(screen.queryByText("En línea")).not.toBeInTheDocument();
    expect(screen.queryByText("Todos los servicios responden")).not.toBeInTheDocument();
    // Y dice cuál, sin tener que bajar a buscarlo.
    expect(screen.getByText("Revisa: Redis")).toBeInTheDocument();
  });

  it("el esquema atrasado sale en la cabecera y en los componentes", async () => {
    montar({ ...SANO, status: "degraded", schema_revision: "behind (v140 < v146)" });

    expect(await screen.findByText("Desalineado")).toBeInTheDocument();
    const componentes = screen.getByRole("region", { name: "Componentes" });
    expect(within(componentes).getByText("Esquema de la base de datos")).toBeInTheDocument();
    expect(within(componentes).getByText("behind (v140 < v146)")).toBeInTheDocument();
  });

  it("un componente que no se mide no lleva insignia de error", async () => {
    montar({ ...SANO, redis: "unconfigured" });

    const componentes = await screen.findByRole("region", { name: "Componentes" });
    expect(within(componentes).getByText("Sin medir")).toBeInTheDocument();
    expect(within(componentes).queryByText("Error")).not.toBeInTheDocument();
  });

  it("no enseña una celda de versión que la API nunca manda", async () => {
    montar(SANO);

    await screen.findByText("En línea");
    expect(screen.queryByText("Versión de la API")).not.toBeInTheDocument();
  });

  it("con la API caída lo dice como caída", async () => {
    montar({ detail: "boom" }, { status: 500 });

    expect(await screen.findByText("Sin conexión")).toBeInTheDocument();
  });

  it("a un administrador le enseña lo que falla en el navegador", async () => {
    const fetchMock = montar(SANO, { admin: true });

    expect(await screen.findByText("Cannot read properties of undefined")).toBeInTheDocument();
    expect(screen.getByText("/radar")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => callUrl(c).includes("/security/client-errors"))).toBe(true);
  });

  it("sin permisos no pide los errores del navegador", async () => {
    const fetchMock = montar(SANO, { admin: false });

    await screen.findByText("En línea");
    expect(fetchMock.mock.calls.some((c) => callUrl(c).includes("/security/client-errors"))).toBe(false);
    expect(screen.queryByText("Errores en el navegador")).not.toBeInTheDocument();
  });
});
