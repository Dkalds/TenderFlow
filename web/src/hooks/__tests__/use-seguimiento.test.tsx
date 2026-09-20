/**
 * `useSeguimiento` y `SeguirBoton` como control único (ADR-031 §C).
 *
 * Lo que se fija:
 *
 * 1. **El enrutado por tipo.** Mientras dura la escritura doble de ADR-031 §B,
 *    un expediente se sigue por `/watchlist/items` y una empresa por
 *    `/competitive/watchlist` —que escriben su tabla y `follows`—; el resto por
 *    `/follows`. Si el control único escribiera sólo en `follows`, el favorito
 *    marcado en el Radar no aparecería en «Mi watchlist».
 * 2. **Sólo se pide la fuente que toca.** Las otras dos consultas se instancian
 *    pero no salen a la red.
 * 3. **Una empresa deduplicada se alterna entera**: sus `empresa_id`
 *    equivalentes van en una sola mutación.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { fuenteDe } from "@/hooks/use-seguimiento";
import { SeguirBoton } from "@/components/seguir-boton";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

function crearCliente() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** Responde por ruta y método, y deja un registro de lo pedido. */
function servidor(rutas: Record<string, unknown>) {
  return vi.fn().mockImplementation((...args: unknown[]) => {
    const clave = `${callMethod(args)} ${callUrl(args).split("?")[0]}`;
    const cuerpo = clave in rutas ? rutas[clave] : { items: [] };
    return Promise.resolve(jsonResponse(cuerpo, clave.startsWith("POST") ? 201 : 200));
  });
}

function pedidas(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((c) => `${callMethod(c)} ${callUrl(c).split("?")[0]}`);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("fuenteDe", () => {
  it("enruta cada tipo a su endpoint mientras dura la escritura doble", () => {
    expect(fuenteDe("licitacion", "seguir")).toBe("favoritos");
    expect(fuenteDe("empresa", "seguir")).toBe("empresas");
    expect(fuenteDe("organo", "seguir")).toBe("follows");
    expect(fuenteDe("cpv", "seguir")).toBe("follows");
    // Un descarte no es un favorito: va por `follows` aunque sea un expediente.
    expect(fuenteDe("licitacion", "descartar")).toBe("follows");
  });
});

describe("SeguirBoton sobre un expediente", () => {
  it("lee y escribe por los favoritos, y no pide las otras dos fuentes", async () => {
    const fetchMock = servidor({
      "GET /api/v1/watchlist/items": { items: [] },
      "POST /api/v1/watchlist/items": { id: 9, id_externo: "LIC-1" },
    });
    vi.stubGlobal("fetch", fetchMock);
    const onAlternar = vi.fn();

    render(
      <QueryClientProvider client={crearCliente()}>
        <SeguirBoton
          targetType="licitacion"
          targetId="LIC-1"
          etiqueta="Mantenimiento SAP"
          onAlternar={onAlternar}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    expect(screen.getByRole("button")).toHaveAccessibleName("Seguir Mantenimiento SAP");

    fireEvent.click(screen.getByRole("button"));
    expect(onAlternar).toHaveBeenCalledWith(true);
    await waitFor(() => expect(pedidas(fetchMock)).toContain("POST /api/v1/watchlist/items"));

    const todas = pedidas(fetchMock);
    expect(todas.some((p) => p.includes("/follows"))).toBe(false);
    expect(todas.some((p) => p.includes("/competitive/watchlist"))).toBe(false);
  });

  it("respeta el nombre accesible de la pantalla", async () => {
    vi.stubGlobal(
      "fetch",
      servidor({ "GET /api/v1/watchlist/items": { items: [{ id: 1, id_externo: "LIC-1" }] } }),
    );

    render(
      <QueryClientProvider client={crearCliente()}>
        <SeguirBoton
          targetType="licitacion"
          targetId="LIC-1"
          variante="icono"
          nombreAccesible={{ seguir: "Añadir a favoritos", dejar: "Quitar de favoritos" }}
        />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveAccessibleName("Quitar de favoritos"),
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("SeguirBoton sobre una empresa", () => {
  it("alterna el grupo de identidades equivalentes por la vigilancia de empresas", async () => {
    const fetchMock = servidor({ "GET /api/v1/competitive/watchlist": { items: [] } });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <QueryClientProvider client={crearCliente()}>
        <SeguirBoton
          targetType="empresa"
          targetId="7"
          equivalentes={["7", "8"]}
          icono="ojo"
          nombreAccesible="visible"
          textos={{ seguir: "Vigilar empresa", siguiendo: "Vigilando" }}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Vigilar empresa" }));

    await waitFor(() =>
      expect(pedidas(fetchMock).filter((p) => p === "POST /api/v1/competitive/watchlist")).toHaveLength(
        2,
      ),
    );
    expect(pedidas(fetchMock).some((p) => p.includes("/follows"))).toBe(false);
  });
});
