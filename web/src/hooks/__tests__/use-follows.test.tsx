/**
 * Tests de `use-follows` y del control `SeguirBoton` (ADR-031).
 *
 * Lo que se fija aquí es lo que hace que un solo componente pueda sustituir a
 * tres, que es la promesa de ADR-031 §C:
 *
 * 1. **La lectura va acotada por tipo.** Una sola clave de caché para todo
 *    haría que seguir un órgano invalidara la lista de empresas y que las dos
 *    pantallas parpadearan a la vez.
 * 2. **El alta y la baja son optimistas y reversibles.** El estado cambia en el
 *    frame del clic y vuelve solo si el servidor dice que no. Sin la vuelta
 *    atrás, un fallo de red deja el control mintiendo.
 * 3. **La telemetría se emite después del 200, no antes** — el mismo error que
 *    ya se corrigió en las descargas, donde cada intento fallido contaba como
 *    exportación.
 * 4. **El control dice su estado con texto y con `aria-pressed`**, no sólo con
 *    color: es un alternador y tiene que leerse sin ver.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { renderHook, render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { toast } from "sonner";
import { registrarEvento } from "@/lib/analytics";
import { useFollows, useSeguir, useDejarDeSeguir, type Follow } from "@/hooks/use-follows";
import { SeguirBoton } from "@/components/seguir-boton";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

const ORGANO: Follow = {
  id: 1,
  target_type: "organo",
  target_id: "Ayuntamiento de Madrid",
  kind: "seguir",
  visibility: "private",
  created_at: "2026-09-01T00:00:00Z",
};

/**
 * Respuestas **reales** y una por llamada.
 *
 * Un `Response` sólo se puede leer una vez, así que `mockResolvedValue(res)` con
 * el mismo objeto deja la segunda petición colgada sin cuerpo — que es lo que
 * hacía fallar «dos tipos son dos listas» sin decir por qué. Se construye una
 * nueva en cada invocación.
 */
function respuestas(...cuerpos: Array<[unknown, number]>) {
  let i = 0;
  return vi.fn().mockImplementation(() => {
    const [cuerpo, estado] = cuerpos[Math.min(i++, cuerpos.length - 1)];
    return Promise.resolve(jsonResponse(cuerpo, estado));
  });
}

function crearCliente() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function envoltorio(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

beforeEach(() => {
  vi.mocked(registrarEvento).mockClear();
  vi.mocked(toast.error).mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useFollows", () => {
  it("pide sólo el tipo que le interesa a la pantalla", async () => {
    const fetchMock = respuestas([{ items: [ORGANO], total: 1 }, 200]);
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result } = renderHook(() => useFollows("organo"), { wrapper: envoltorio(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([ORGANO]);
    const url = callUrl(fetchMock.mock.calls[0]);
    expect(url.startsWith("/api/v1/follows")).toBe(true);
    expect(url).toContain("target_type=organo");
    // Sin `kind` el backend devolvería también los descartes, que en esta
    // pantalla no son seguimientos sino lo contrario.
    expect(url).toContain("kind=seguir");
  });

  it("cachea por tipo: dos tipos son dos listas", async () => {
    vi.stubGlobal("fetch", respuestas([{ items: [], total: 0 }, 200]));
    const qc = crearCliente();

    const { result } = renderHook(
      () => ({ organos: useFollows("organo"), empresas: useFollows("empresa") }),
      { wrapper: envoltorio(qc) },
    );
    await waitFor(() => expect(result.current.organos.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.empresas.isSuccess).toBe(true));

    expect(qc.getQueryData(["follows", "organo", "seguir"])).toEqual([]);
    expect(qc.getQueryData(["follows", "empresa", "seguir"])).toEqual([]);
  });
});

describe("useSeguir", () => {
  it("marca en el acto y mide después del 200", async () => {
    vi.stubGlobal("fetch", respuestas([ORGANO, 201]));
    const qc = crearCliente();
    qc.setQueryData(["follows", "organo", "seguir"], []);

    const { result } = renderHook(() => useSeguir("organo"), { wrapper: envoltorio(qc) });
    await act(async () => {
      await result.current.mutateAsync("Ayuntamiento de Madrid");
    });

    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "seguir" });
  });

  it("deshace el optimismo y avisa si el servidor dice que no", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const qc = crearCliente();
    qc.setQueryData(["follows", "organo", "seguir"], []);

    const { result } = renderHook(() => useSeguir("organo"), { wrapper: envoltorio(qc) });
    await act(async () => {
      await result.current.mutateAsync("X").catch(() => undefined);
    });

    expect(qc.getQueryData(["follows", "organo", "seguir"])).toEqual([]);
    expect(toast.error).toHaveBeenCalled();
    // Un intento fallido no es uso del producto.
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});

describe("useDejarDeSeguir", () => {
  it("borra por la ruta del objetivo, con el identificador escapado", async () => {
    const fetchMock = respuestas([{}, 200]);
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();
    qc.setQueryData(["follows", "organo", "seguir"], [ORGANO]);

    const { result } = renderHook(() => useDejarDeSeguir("organo"), { wrapper: envoltorio(qc) });
    await act(async () => {
      await result.current.mutateAsync("Ayuntamiento de Madrid");
    });

    expect(callMethod(fetchMock.mock.calls[0])).toBe("DELETE");
    // Los espacios (y en licitaciones, las barras de PLACSP) tienen que viajar
    // escapados o el router no casa la ruta.
    expect(callUrl(fetchMock.mock.calls[0])).toContain(
      "/api/v1/follows/organo/Ayuntamiento%20de%20Madrid",
    );
  });
});

describe("SeguirBoton", () => {
  it("dice su estado con texto y con aria-pressed", async () => {
    vi.stubGlobal("fetch", respuestas([{ items: [ORGANO], total: 1 }, 200]));
    const qc = crearCliente();

    render(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(SeguirBoton, {
          targetType: "organo",
          targetId: "Ayuntamiento de Madrid",
          etiqueta: "el órgano X",
        }),
      ),
    );

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button")).toHaveTextContent("Siguiendo");
    expect(screen.getByRole("button")).toHaveAccessibleName("Dejar de seguir el órgano X");
  });

  it("alterna al hacer clic sobre algo que no se sigue", async () => {
    // Las tres llamadas del ciclo completo, en orden: la lista vacía, el alta,
    // y la relectura que dispara `onSettled`. Con sólo dos, la invalidación
    // recibiría el cuerpo del POST como si fuera una lista y el control
    // acabaría leyendo basura — que es peor que un test en rojo.
    const fetchMock = respuestas(
      [{ items: [], total: 0 }, 200],
      [ORGANO, 201],
      [{ items: [ORGANO], total: 1 }, 200],
    );
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    render(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(SeguirBoton, {
          targetType: "organo",
          targetId: "Ayuntamiento de Madrid",
        }),
      ),
    );

    // Se espera a que el control esté **habilitado**, no sólo a que diga
    // `aria-pressed="false"`: eso ya es cierto mientras carga —todavía no sigue
    // nada— y hacer clic ahí es hacer clic en un botón `disabled`, que no
    // dispara nada y deja el test verde por el motivo equivocado.
    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button")).toHaveTextContent("Seguir");

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button")).toHaveTextContent("Siguiendo");
    expect(callMethod(fetchMock.mock.calls[1])).toBe("POST");
  });
});
