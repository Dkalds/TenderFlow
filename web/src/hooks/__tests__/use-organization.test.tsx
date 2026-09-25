/**
 * Qué organización queda activa cuando nadie ha elegido una.
 *
 * `GET /organizations` pone la personal primero. Quedarse con la primera dejaba
 * a un owner de equipo con Mi Pipeline y Dirección vacíos hasta que encontraba
 * el selector del menú de cuenta: el trabajo compartido vive en el equipo.
 */
import * as React from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import {
  olvidarOrganizacionPorDefecto,
  organizacionPorDefecto,
  organizacionResuelta,
  useActiveOrganizationId,
  useOrganizations,
  useOrganizationStore,
  type Organization,
} from "@/hooks/use-organization";
import { callUrl, jsonResponse } from "./fetch-call";

function org(id: number, is_personal: boolean): Organization {
  return {
    id,
    is_personal,
    name: is_personal ? "Personal" : `Equipo ${id}`,
    role: "owner",
    created_at: "2026-09-01T10:00:00Z",
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function servirOrganizaciones(organizations: Organization[]) {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation((...call: unknown[]) =>
        Promise.resolve(jsonResponse(callUrl(call).includes("/organizations") ? organizations : {})),
      ),
  );
}

afterEach(() => {
  // Desmontar antes de limpiar el store: un hook aún montado recibe su
  // `/organizations` tarde y apuntaría la de por defecto en la caché después de
  // limpiarla, y el test siguiente la heredaría.
  cleanup();
  useOrganizationStore.setState({ activeOrganizationId: null, ultimaPorDefecto: undefined });
  vi.unstubAllGlobals();
});

describe("organizacionPorDefecto", () => {
  it("prefiere la de equipo aunque la personal venga primero", () => {
    expect(organizacionPorDefecto([org(9, true), org(21, false)])).toBe(21);
  });

  it("con varios equipos toma el primero en el orden del servidor", () => {
    expect(organizacionPorDefecto([org(9, true), org(30, false), org(21, false)])).toBe(30);
  });

  it("sin equipo cae en la personal", () => {
    expect(organizacionPorDefecto([org(9, true)])).toBe(9);
  });

  it("sin organizaciones no inventa ninguna", () => {
    expect(organizacionPorDefecto([])).toBeNull();
  });
});

describe("useActiveOrganizationId", () => {
  it("sin elección guardada, arranca en el equipo", async () => {
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(21));
  });

  it("una elección guardada manda sobre el valor por defecto", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 9 });
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(9));
  });

  /**
   * Los tres estados, que antes eran dos.
   *
   * «Todavía no lo sé» y «no hay ninguna» compartían el mismo `null`, así que
   * toda consulta con ámbito salía en el primer render preguntando por la
   * organización personal. En la ficha de una oportunidad eso era un 404 con
   * toast rojo en cada apertura, corregido medio segundo después por la
   * petición buena.
   */
  it("mientras el listado está en vuelo no dice que no haya ninguna", async () => {
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    expect(result.current).toBeUndefined();
    expect(organizacionResuelta(result.current)).toBe(false);

    await waitFor(() => expect(result.current).toBe(21));
    expect(organizacionResuelta(result.current)).toBe(true);
  });

  it("sin ninguna organización resuelve a null, que sí es una respuesta", async () => {
    // El estado que no hay que confundir con el de arriba: aquí ya se sabe, y
    // omitir `organization_id` es lo correcto —el backend resuelve la personal—,
    // así que las consultas con ámbito tienen que salir igualmente.
    servirOrganizaciones([]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(organizacionResuelta(result.current)).toBe(true));
    expect(result.current).toBeNull();
  });

  it("si el listado falla deja de esperar en vez de retener las consultas", async () => {
    // Retenerlas para siempre dejaría el dashboard entero en esqueleto por una
    // sola petición caída. Se vuelve al comportamiento de siempre: preguntar
    // sin ámbito y que el backend resuelva la personal.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("sin red")));

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(organizacionResuelta(result.current)).toBe(true));
    expect(result.current).toBeNull();
  });

  it("una elección que ya no es de la persona no se respeta", async () => {
    // Sacaron a la persona del equipo 40: seguir mandándolo daría 403 en cada
    // pantalla con ámbito.
    useOrganizationStore.setState({ activeOrganizationId: 40 });
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(21));
  });
});

/**
 * Sin elección guardada, cada carga completa esperaba a `/organizations` antes
 * de lanzar el Radar, la Agenda, las oportunidades y las métricas: un viaje de
 * ida y vuelta entero para acabar casi siempre en la misma organización. Ahora
 * se adelanta la última por defecto que confirmó el listado, y el listado la
 * corrige si ha dejado de valer.
 */
describe("useActiveOrganizationId — organización por defecto adelantada", () => {
  /** `/organizations` que no contesta hasta que se libere. */
  function organizacionesEnVuelo(organizations: Organization[]) {
    let liberar: () => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            liberar = () => resolve(jsonResponse(organizations));
          }),
      ),
    );
    return { liberar: () => liberar() };
  }

  it("recuerda la organización por defecto que confirma el listado", async () => {
    servirOrganizaciones([org(9, true), org(21, false)]);
    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(21));
    await waitFor(() => expect(useOrganizationStore.getState().ultimaPorDefecto).toBe(21));
  });

  it("con una recordada, la entrega desde el primer render sin esperar al listado", () => {
    useOrganizationStore.setState({ ultimaPorDefecto: 21 });
    organizacionesEnVuelo([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    expect(result.current).toBe(21);
    expect(organizacionResuelta(result.current)).toBe(true);
  });

  it("si la recordada ya no vale, el listado la corrige y la caché se actualiza", async () => {
    // La recordada es el equipo 40, del que la persona ya no es miembro.
    useOrganizationStore.setState({ ultimaPorDefecto: 40 });
    const api = organizacionesEnVuelo([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });
    expect(result.current).toBe(40);

    api.liberar();
    await waitFor(() => expect(result.current).toBe(21));
    await waitFor(() => expect(useOrganizationStore.getState().ultimaPorDefecto).toBe(21));
  });

  it("también recuerda que no hay ninguna: `null` sale sin esperar la próxima vez", async () => {
    servirOrganizaciones([]);
    const primera = renderHook(() => useActiveOrganizationId(), { wrapper });
    await waitFor(() => expect(useOrganizationStore.getState().ultimaPorDefecto).toBeNull());
    primera.unmount();

    organizacionesEnVuelo([]);
    const segunda = renderHook(() => useActiveOrganizationId(), { wrapper });
    expect(segunda.result.current).toBeNull();
    expect(organizacionResuelta(segunda.result.current)).toBe(true);
  });

  it("una elección guardada sigue mandando sobre la recordada", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 9, ultimaPorDefecto: 30 });
    const api = organizacionesEnVuelo([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });
    expect(result.current).toBe(9);

    api.liberar();
    // La caché apunta la de por defecto (para cuando no haya elección)…
    await waitFor(() => expect(useOrganizationStore.getState().ultimaPorDefecto).toBe(21));
    // …pero la activa sigue siendo la elegida.
    expect(result.current).toBe(9);
  });

  it("si el listado falla, sigue con la recordada en vez de saltar a la personal", async () => {
    useOrganizationStore.setState({ ultimaPorDefecto: 21 });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("sin red")));

    const { result } = renderHook(() => ({ activa: useActiveOrganizationId(), listado: useOrganizations() }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.listado.isError).toBe(true));
    expect(result.current.activa).toBe(21);
    expect(useOrganizationStore.getState().ultimaPorDefecto).toBe(21);
  });

  it("el HTML del servidor y la hidratación no ven la caché: no hay desajuste", async () => {
    // El servidor no tiene `localStorage`; si el primer render del cliente
    // leyera la caché, pintaría otra cosa que el HTML y React tendría que
    // descartarlo. zustand entrega el estado inicial durante la hidratación.
    useOrganizationStore.setState({ ultimaPorDefecto: 21 });
    const api = organizacionesEnVuelo([org(9, true), org(21, false)]);

    function Organizacion() {
      const id = useActiveOrganizationId();
      return <span data-testid="org">{id === undefined ? "pendiente" : String(id)}</span>;
    }
    const conCliente = () => (
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Organizacion />
      </QueryClientProvider>
    );

    const contenedor = document.createElement("div");
    contenedor.innerHTML = renderToString(conCliente());
    // El servidor no conoce la caché: pinta «pendiente».
    expect(contenedor.textContent).toBe("pendiente");
    document.body.appendChild(contenedor);

    const erroresRecuperables = vi.fn();
    let raiz: ReturnType<typeof hydrateRoot> | undefined;
    await act(async () => {
      raiz = hydrateRoot(contenedor, conCliente(), { onRecoverableError: erroresRecuperables });
    });

    // Tras hidratar sin desajustes, el cliente ya usa la recordada.
    expect(erroresRecuperables).not.toHaveBeenCalled();
    expect(contenedor.textContent).toBe("21");

    api.liberar();
    await act(async () => {
      raiz?.unmount();
    });
    contenedor.remove();
  });
});

describe("olvidarOrganizacionPorDefecto", () => {
  it("olvida la por defecto recordada y conserva la elegida", () => {
    // La recordada es una apuesta de este navegador, no una decisión de la
    // persona: al empezar sesión puede ser de otra. La elegida sí lo es.
    useOrganizationStore.setState({ activeOrganizationId: 9, ultimaPorDefecto: 21 });

    olvidarOrganizacionPorDefecto();

    const estado = useOrganizationStore.getState();
    expect(estado.ultimaPorDefecto).toBeUndefined();
    expect(estado.activeOrganizationId).toBe(9);
  });
});
