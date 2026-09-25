/**
 * `useSeguimiento` y `SeguirBoton` como control único (ADR-031 §C).
 *
 * Lo que se fija:
 *
 * 1. **El enrutado por tipo.** Mientras dura la escritura doble de ADR-031 §B,
 *    un expediente se sigue por `/watchlist/items` y una empresa por
 *    `/competitive/watchlist` —que escriben su tabla y `follows`—; un órgano
 *    por `/cuentas`, y el resto por `/follows`. Si el control único escribiera
 *    sólo en `follows`, el favorito marcado en el Radar no aparecería en «Mi
 *    watchlist», y el órgano seguido en Mercado no avisaría a nadie —que es
 *    lo que pasaba hasta 2026-09-25—.
 * 2. **Sólo se pide la fuente que toca.** Las demás consultas se instancian
 *    pero no salen a la red.
 * 3. **Una empresa deduplicada se alterna entera**: sus `empresa_id`
 *    equivalentes van en una sola mutación.
 * 4. **Un órgano es una cuenta de la organización activa**, y si lo es lo
 *    contesta el servidor por el nombre del órgano: el cliente no pliega.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { registrarEvento } from "@/lib/analytics";
import { fuenteDe } from "@/hooks/use-seguimiento";
import { useOrganizationStore } from "@/hooks/use-organization";
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
    // La cuenta objetivo de la organización: el único seguir-órgano con avisos.
    expect(fuenteDe("organo", "seguir")).toBe("cuentas");
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
    expect(todas.some((p) => p.includes("/cuentas"))).toBe(false);
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
    expect(pedidas(fetchMock).some((p) => p.includes("/cuentas"))).toBe(false);
  });
});

// ── Órganos: la cuenta de la organización ───────────────────────────────────

const EQUIPO = { id: 21, name: "Equipo", role: "member", is_personal: false };
const ALCALA = {
  id: 7,
  organization_id: 21,
  nombre: "Ayuntamiento de Alcalá",
  organo_nombre: "Ayuntamiento de Alcalá",
  organo_norm: "ayuntamiento de alcala",
  created_at: "2026-09-20T00:00:00Z",
};

/**
 * Servidor con estado para las cuentas: lo que contesta `GET /cuentas` depende
 * de las altas y bajas anteriores, como en la API. `"pendiente"` deja la lista
 * de organizaciones sin contestar.
 */
function servidorDeCuentas({
  siguiendo,
  organizaciones = [EQUIPO],
}: {
  siguiendo: boolean;
  organizaciones?: unknown[] | "pendiente";
}) {
  let cuenta: typeof ALCALA | null = siguiendo ? ALCALA : null;
  return vi.fn().mockImplementation((...args: unknown[]) => {
    const metodo = callMethod(args);
    const ruta = callUrl(args).split("?")[0];
    if (ruta === "/api/v1/organizations") {
      return organizaciones === "pendiente"
        ? new Promise(() => undefined)
        : Promise.resolve(jsonResponse(organizaciones));
    }
    if (metodo === "GET" && ruta === "/api/v1/cuentas") {
      return Promise.resolve(jsonResponse(cuenta ? [cuenta] : []));
    }
    if (metodo === "POST" && ruta === "/api/v1/cuentas") {
      cuenta = ALCALA;
      return Promise.resolve(jsonResponse(ALCALA, 201));
    }
    if (metodo === "DELETE" && ruta === "/api/v1/cuentas/por-organo") {
      cuenta = null;
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(jsonResponse({ items: [] }));
  });
}

/** `MÉTODO /ruta?query` de cada llamada: aquí la query es parte de lo que se fija. */
function conQuery(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((c) => `${callMethod(c)} ${callUrl(c)}`);
}

describe("SeguirBoton sobre un órgano", () => {
  beforeEach(() => {
    vi.mocked(registrarEvento).mockClear();
    // Sin organización elegida: resuelve a la primera de equipo (la 21). Y sin
    // la por defecto recordada, que un test anterior deja escrita y se adelanta
    // a `/organizations`: con ella la organización ya «se sabe» desde el primer
    // render.
    useOrganizationStore.setState({ activeOrganizationId: null, ultimaPorDefecto: undefined });
  });

  function pintar() {
    render(
      <QueryClientProvider client={crearCliente()}>
        <SeguirBoton
          targetType="organo"
          targetId="AYUNTAMIENTO DE ALCALÁ"
          etiqueta="el órgano Alcalá"
          variante="icono"
        />
      </QueryClientProvider>,
    );
  }

  it("pregunta a /cuentas por su órgano en la organización activa, no a /follows", async () => {
    const fetchMock = servidorDeCuentas({ siguiendo: true });
    vi.stubGlobal("fetch", fetchMock);
    pintar();

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button")).toHaveAccessibleName("Dejar de seguir el órgano Alcalá");
    const consulta = conQuery(fetchMock).find((p) => p.startsWith("GET /api/v1/cuentas")) ?? "";
    const params = new URL(consulta.split(" ")[1] ?? "", "http://localhost").searchParams;
    // La grafía viaja tal cual: casarla con la cuenta es cosa del servidor.
    expect(params.get("organo")).toBe("AYUNTAMIENTO DE ALCALÁ");
    expect(params.get("organization_id")).toBe("21");
    expect(conQuery(fetchMock).some((p) => p.includes("/follows"))).toBe(false);
  });

  it("seguir da de alta la cuenta del equipo y lo mide una vez", async () => {
    const fetchMock = servidorDeCuentas({ siguiendo: false });
    vi.stubGlobal("fetch", fetchMock);
    pintar();

    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(registrarEvento).toHaveBeenCalledTimes(1));
    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "seguir" });
    expect(conQuery(fetchMock)).toContain("POST /api/v1/cuentas?organization_id=21");
    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    expect(conQuery(fetchMock).some((p) => p.includes("/follows"))).toBe(false);
  });

  it("dejar de seguir quita el órgano por su nombre, no la cuenta por su id", async () => {
    // Desde v145 una cuenta puede tener varios órganos: quitar la estrella de
    // uno no puede borrar los demás, y qué entrada de la cuenta es la de este
    // botón sólo lo sabe el servidor, que pliega el nombre.
    const fetchMock = servidorDeCuentas({ siguiendo: true });
    vi.stubGlobal("fetch", fetchMock);
    pintar();

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(conQuery(fetchMock)).toContain(
        "DELETE /api/v1/cuentas/por-organo?organo=AYUNTAMIENTO+DE+ALCAL%C3%81&organization_id=21",
      ),
    );
    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"));
    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "dejar_de_seguir" });
  });

  it("no se puede pulsar mientras no se sabe la organización", async () => {
    const fetchMock = servidorDeCuentas({ siguiendo: false, organizaciones: "pendiente" });
    vi.stubGlobal("fetch", fetchMock);
    pintar();

    // Un clic aquí seguiría el órgano en la organización personal, donde sólo
    // le avisaría a quien lo pulsó.
    await waitFor(() =>
      expect(conQuery(fetchMock).some((p) => p.includes("/organizations"))).toBe(true),
    );
    expect(screen.getByRole("button")).toBeDisabled();
    expect(conQuery(fetchMock).some((p) => p.includes("/cuentas"))).toBe(false);
  });
});
