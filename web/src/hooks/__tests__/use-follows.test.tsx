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
 * 3. **Sin telemetría propia.** Hasta 2026-09-25 emitía `organo_seguido` con
 *    cualquier alta —también un CPV—, y ese evento mide si se trabaja por
 *    cuentas: lo emite `use-cuentas`, que es donde seguir un órgano tiene
 *    efecto. Los órganos ya no pasan por aquí (ver `use-seguimiento`), así que
 *    estos tests usan un CPV y un lote, que sí.
 * 4. **El control dice su estado con texto y con `aria-pressed`**, no sólo con
 *    color: es un alternador y tiene que leerse sin ver.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { renderHook, render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));
// `SeguirBoton` instancia también la fuente de cuentas, que pregunta por la
// organización activa: en blanco, para que las respuestas en orden de este
// fichero sigan siendo las de `/follows` (las cuentas tienen su propio test).
vi.mock("@/hooks/use-cuentas", () => ({
  useCuentaDeOrgano: () => ({ data: undefined, isPending: false }),
  useSeguirCuenta: () => ({ mutate: vi.fn(), isPending: false }),
  useDejarDeSeguirOrgano: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { toast } from "sonner";
import { registrarEvento } from "@/lib/analytics";
import { useFollows, useSeguir, useDejarDeSeguir, type Follow } from "@/hooks/use-follows";
import { SeguirBoton } from "@/components/seguir-boton";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

const CPV: Follow = {
  id: 1,
  target_type: "cpv",
  target_id: "72260000",
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
    const fetchMock = respuestas([{ items: [CPV], total: 1 }, 200]);
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result } = renderHook(() => useFollows("cpv"), { wrapper: envoltorio(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([CPV]);
    const url = callUrl(fetchMock.mock.calls[0]);
    expect(url.startsWith("/api/v1/follows")).toBe(true);
    expect(url).toContain("target_type=cpv");
    // Sin `kind` el backend devolvería también los descartes, que en esta
    // pantalla no son seguimientos sino lo contrario.
    expect(url).toContain("kind=seguir");
  });

  it("cachea por tipo: dos tipos son dos listas", async () => {
    vi.stubGlobal("fetch", respuestas([{ items: [], total: 0 }, 200]));
    const qc = crearCliente();

    const { result } = renderHook(
      () => ({ cpvs: useFollows("cpv"), empresas: useFollows("empresa") }),
      { wrapper: envoltorio(qc) },
    );
    await waitFor(() => expect(result.current.cpvs.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.empresas.isSuccess).toBe(true));

    expect(qc.getQueryData(["follows", "cpv", "seguir"])).toEqual([]);
    expect(qc.getQueryData(["follows", "empresa", "seguir"])).toEqual([]);
  });
});

describe("useSeguir", () => {
  it("marca en el acto y no mide nada por su cuenta", async () => {
    vi.stubGlobal("fetch", respuestas([CPV, 201]));
    const qc = crearCliente();
    qc.setQueryData(["follows", "cpv", "seguir"], []);

    const { result } = renderHook(() => useSeguir("cpv"), { wrapper: envoltorio(qc) });
    await act(async () => {
      await result.current.mutateAsync("72260000");
    });

    // `organo_seguido` mide el trabajo por cuentas y lo emite `use-cuentas`;
    // seguir un CPV no es eso.
    expect(registrarEvento).not.toHaveBeenCalled();
  });

  it("deshace el optimismo y avisa si el servidor dice que no", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const qc = crearCliente();
    qc.setQueryData(["follows", "cpv", "seguir"], []);

    const { result } = renderHook(() => useSeguir("cpv"), { wrapper: envoltorio(qc) });
    await act(async () => {
      await result.current.mutateAsync("X").catch(() => undefined);
    });

    expect(qc.getQueryData(["follows", "cpv", "seguir"])).toEqual([]);
    expect(toast.error).toHaveBeenCalled();
  });
});

describe("useDejarDeSeguir", () => {
  it("borra por la ruta del objetivo, con el identificador escapado", async () => {
    const fetchMock = respuestas([{}, 200]);
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();
    qc.setQueryData(["follows", "lote", "seguir"], []);

    const { result } = renderHook(() => useDejarDeSeguir("lote"), { wrapper: envoltorio(qc) });
    await act(async () => {
      await result.current.mutateAsync("PA-S 2026/000058#2");
    });

    expect(callMethod(fetchMock.mock.calls[0])).toBe("DELETE");
    // Los espacios y las barras de PLACSP tienen que viajar escapados o el
    // router no casa la ruta.
    expect(callUrl(fetchMock.mock.calls[0])).toContain(
      "/api/v1/follows/lote/PA-S%202026%2F000058%232",
    );
  });
});

describe("SeguirBoton", () => {
  it("dice su estado con texto y con aria-pressed", async () => {
    vi.stubGlobal("fetch", respuestas([{ items: [CPV], total: 1 }, 200]));
    const qc = crearCliente();

    render(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(SeguirBoton, {
          targetType: "cpv",
          targetId: "72260000",
          etiqueta: "el CPV 72260000",
        }),
      ),
    );

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button")).toHaveTextContent("Siguiendo");
    expect(screen.getByRole("button")).toHaveAccessibleName("Dejar de seguir el CPV 72260000");
  });

  it("alterna al hacer clic sobre algo que no se sigue", async () => {
    // Las tres llamadas del ciclo completo, en orden: la lista vacía, el alta,
    // y la relectura que dispara `onSettled`. Con sólo dos, la invalidación
    // recibiría el cuerpo del POST como si fuera una lista y el control
    // acabaría leyendo basura — que es peor que un test en rojo.
    const fetchMock = respuestas(
      [{ items: [], total: 0 }, 200],
      [CPV, 201],
      [{ items: [CPV], total: 1 }, 200],
    );
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    render(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(SeguirBoton, {
          targetType: "cpv",
          targetId: "72260000",
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
