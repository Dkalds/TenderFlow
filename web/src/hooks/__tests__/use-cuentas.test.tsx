/**
 * `use-cuentas` — el único «seguir un órgano» con efectos (F1.5).
 *
 * Lo que se fija:
 *
 * 1. **El ámbito es la organización activa.** Sin `organization_id` el backend
 *    resuelve la personal, y una cuenta creada ahí sólo le avisa a quien la
 *    creó: era el fallo de /cuentas. Mientras no se sabe cuál es, no se pide
 *    nada.
 * 2. **«¿Es cuenta este órgano?» lo contesta el servidor** (`?organo=`), que es
 *    quien pliega el nombre. El cliente manda la grafía tal cual y no compara.
 * 3. **`organo_seguido` se mide aquí, y sólo tras la respuesta**: es el único
 *    seguimiento de órgano con efectos, y un intento fallido no es uso.
 * 4. **Optimista y reversible** sobre la pregunta del botón, con el motivo de
 *    la API en el aviso de error (el 403 del viewer).
 * 5. **Quitar la estrella va por nombre** (`/cuentas/por-organo`): desde v142
 *    una cuenta puede tener varios órganos, y el servidor decide si quita uno
 *    o la cuenta entera.
 * 6. **«Deshacer» rehace la cuenta** con sus órganos, su nota y sus etiquetas.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { toast } from "sonner";
import { registrarEvento } from "@/lib/analytics";
import { useOrganizationStore } from "@/hooks/use-organization";
import {
  useBuscarOrganos,
  useCrearCuenta,
  useCuentaDeOrgano,
  useCuentas,
  useCuentasResumen,
  useDejarDeSeguirCuenta,
  useDejarDeSeguirOrgano,
  useFichaCuenta,
  useRecuperarCuenta,
  useSeguirCuenta,
  type Cuenta,
} from "@/hooks/use-cuentas";
import { cuentaKeys, organizationKeys } from "@/lib/query-keys";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

const PERSONAL = { id: 3, name: "Personal", role: "owner", is_personal: true };
const EQUIPO = { id: 21, name: "Equipo", role: "member", is_personal: false };

const ALCALA: Cuenta = {
  id: 7,
  organization_id: 21,
  nombre: "Ayuntamiento de Alcalá",
  organo_nombre: "Ayuntamiento de Alcalá",
  organo_norm: "ayuntamiento de alcala",
  organos: [
    { id: 70, organo_nombre: "Ayuntamiento de Alcalá", organo_norm: "ayuntamiento de alcala" },
  ],
  created_at: "2026-09-20T00:00:00Z",
};

type Respuesta = readonly [cuerpo: unknown, estado?: number];

/**
 * Responde por método y ruta (sin la query) y deja el registro en el mock.
 * Una ruta puede ser una función, para las que cambian tras una escritura, o
 * `"pendiente"`, para una petición que no contesta nunca.
 */
function servidor(rutas: Record<string, Respuesta | (() => Respuesta) | "pendiente">) {
  return vi.fn().mockImplementation((...args: unknown[]) => {
    const clave = `${callMethod(args)} ${callUrl(args).split("?")[0]}`;
    const ruta = rutas[clave];
    if (ruta === "pendiente") return new Promise(() => undefined);
    const [cuerpo, estado] =
      typeof ruta === "function" ? ruta() : (ruta ?? [{ detail: `sin ruta: ${clave}` }, 404]);
    const codigo = estado ?? (clave.startsWith("POST") ? 201 : 200);
    // Un 204 no puede llevar cuerpo: `new Response("null", { status: 204 })` lanza.
    return Promise.resolve(
      codigo === 204 ? new Response(null, { status: 204 }) : jsonResponse(cuerpo, codigo),
    );
  });
}

/** `MÉTODO /ruta?query` de cada llamada, en orden. */
function pedidas(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((c) => `${callMethod(c)} ${callUrl(c)}`);
}

function query(url: string): URLSearchParams {
  return new URL(url, "http://localhost").searchParams;
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

/** El hook lee la organización al renderizar: se espera a que se sepa. */
async function organizacionResuelta(qc: QueryClient) {
  await waitFor(() => expect(qc.getQueryState(organizationKeys.all)?.status).toBe("success"));
}

beforeEach(() => {
  vi.mocked(registrarEvento).mockClear();
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.success).mockClear();
  // La elección de organización persiste en `localStorage`: cada test parte de
  // «no ha elegido ninguna», que resuelve a la primera de equipo.
  useOrganizationStore.setState({ activeOrganizationId: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useCuentas", () => {
  it("lista las de la organización activa, y no pregunta antes de saber cuál es", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[PERSONAL, EQUIPO]],
      "GET /api/v1/cuentas": [[ALCALA]],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useCuentas(), { wrapper: envoltorio(crearCliente()) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([ALCALA]);
    // Una sola petición y ya con el equipo. Sin esperar, saldría primero sin
    // organización —la personal— y el listado parpadearía con otro ámbito.
    expect(pedidas(fetchMock).filter((p) => p.includes("/cuentas"))).toEqual([
      "GET /api/v1/cuentas?organization_id=21",
    ]);
  });
});

describe("useCuentaDeOrgano", () => {
  it("pregunta al servidor con la grafía del expediente, sin plegarla", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "GET /api/v1/cuentas": [[ALCALA]],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useCuentaDeOrgano("AYUNTAMIENTO DE ALCALÁ"), {
      wrapper: envoltorio(crearCliente()),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(ALCALA);
    const url = pedidas(fetchMock).find((p) => p.includes("/cuentas")) ?? "";
    expect(query(url).get("organo")).toBe("AYUNTAMIENTO DE ALCALÁ");
    expect(query(url).get("organization_id")).toBe("21");
  });

  it("es null si no es cuenta, y sin órgano no pregunta", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "GET /api/v1/cuentas": [[]],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result, rerender } = renderHook(
      ({ organo }: { organo: string | null }) => useCuentaDeOrgano(organo),
      { wrapper: envoltorio(qc), initialProps: { organo: null as string | null } },
    );
    await organizacionResuelta(qc);
    expect(pedidas(fetchMock).some((p) => p.includes("/cuentas"))).toBe(false);

    rerender({ organo: "Ayuntamiento de Soria" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });
});

describe("useSeguirCuenta", () => {
  it("sigue en la organización activa, mide tras el 201 y deja la cuenta real", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "POST /api/v1/cuentas": [ALCALA, 201],
      "GET /api/v1/cuentas": [[ALCALA]],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result } = renderHook(() => useSeguirCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync("AYUNTAMIENTO DE ALCALÁ");
    });

    const alta = fetchMock.mock.calls.find((c) => callMethod(c) === "POST");
    expect(alta).toBeDefined();
    expect(callUrl(alta!)).toBe("/api/v1/cuentas?organization_id=21");
    expect(JSON.parse(String((alta![1] as RequestInit).body))).toEqual({
      organo: "AYUNTAMIENTO DE ALCALÁ",
    });
    expect(registrarEvento).toHaveBeenCalledTimes(1);
    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "seguir" });
    expect(toast.success).toHaveBeenCalledWith(
      "Órgano añadido a la cuenta «Ayuntamiento de Alcalá» de tu organización",
    );
    // La respuesta sustituye a la fila optimista: con el id negativo, dejar de
    // seguir justo después intentaría borrar una cuenta que no existe.
    expect(qc.getQueryData(cuentaKeys.deOrgano(21, "AYUNTAMIENTO DE ALCALÁ"))).toEqual(ALCALA);
  });

  it("marca en el acto, antes de que conteste el servidor", async () => {
    vi.stubGlobal(
      "fetch",
      servidor({ "GET /api/v1/organizations": [[EQUIPO]], "POST /api/v1/cuentas": "pendiente" }),
    );
    const qc = crearCliente();
    const clave = cuentaKeys.deOrgano(21, "Ayuntamiento de Soria");
    qc.setQueryData(clave, null);

    const { result } = renderHook(() => useSeguirCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    act(() => result.current.mutate("Ayuntamiento de Soria"));

    await waitFor(() =>
      expect(qc.getQueryData<Cuenta | null>(clave)).toMatchObject({
        organo_nombre: "Ayuntamiento de Soria",
      }),
    );
    expect(registrarEvento).not.toHaveBeenCalled();
  });

  it("si el servidor dice que no, deshace, enseña su motivo y no mide", async () => {
    vi.stubGlobal(
      "fetch",
      servidor({
        "GET /api/v1/organizations": [[EQUIPO]],
        "POST /api/v1/cuentas": [
          { title: "Forbidden", status: 403, detail: "El rol viewer es de solo lectura." },
          403,
        ],
        "GET /api/v1/cuentas": [[]],
      }),
    );
    const qc = crearCliente();
    const clave = cuentaKeys.deOrgano(21, "Ayuntamiento de Soria");
    qc.setQueryData(clave, null);

    const { result } = renderHook(() => useSeguirCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync("Ayuntamiento de Soria").catch(() => undefined);
    });

    expect(qc.getQueryData(clave)).toBeNull();
    expect(toast.error).toHaveBeenCalledWith("El rol viewer es de solo lectura.");
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});

describe("useDejarDeSeguirCuenta", () => {
  it("borra por id en la organización activa, la quita de la lista y mide la baja", async () => {
    let borrada = false;
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "DELETE /api/v1/cuentas/7": () => {
        borrada = true;
        return [null, 204];
      },
      "GET /api/v1/cuentas": () => [borrada ? [] : [ALCALA]],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();
    qc.setQueryData(cuentaKeys.lista(21), [ALCALA]);

    const { result } = renderHook(() => useDejarDeSeguirCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync({ id: 7 });
    });

    expect(pedidas(fetchMock)).toContain("DELETE /api/v1/cuentas/7?organization_id=21");
    expect(qc.getQueryData(cuentaKeys.lista(21))).toEqual([]);
    expect(registrarEvento).toHaveBeenCalledTimes(1);
    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "dejar_de_seguir" });
  });

  it("si falla, devuelve la cuenta a la lista, enseña el motivo y no mide", async () => {
    vi.stubGlobal(
      "fetch",
      servidor({
        "GET /api/v1/organizations": [[EQUIPO]],
        "DELETE /api/v1/cuentas/7": [{ detail: "Esa cuenta no existe en tu organización." }, 404],
        "GET /api/v1/cuentas": [[ALCALA]],
      }),
    );
    const qc = crearCliente();
    qc.setQueryData(cuentaKeys.lista(21), [ALCALA]);

    const { result } = renderHook(() => useDejarDeSeguirCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync({ id: 7 }).catch(() => undefined);
    });

    expect(qc.getQueryData(cuentaKeys.lista(21))).toEqual([ALCALA]);
    expect(toast.error).toHaveBeenCalledWith("Esa cuenta no existe en tu organización.");
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});

describe("useDejarDeSeguirOrgano", () => {
  it("quita por nombre, desmarca el botón en el acto y mide la baja", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "DELETE /api/v1/cuentas/por-organo": [null, 204],
      "GET /api/v1/cuentas": [[]],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();
    const clave = cuentaKeys.deOrgano(21, "AYUNTAMIENTO DE ALCALÁ");
    qc.setQueryData(clave, ALCALA);

    const { result } = renderHook(() => useDejarDeSeguirOrgano(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync("AYUNTAMIENTO DE ALCALÁ");
    });

    const baja = pedidas(fetchMock).find((p) => p.startsWith("DELETE")) ?? "";
    expect(baja.split("?")[0]).toBe("DELETE /api/v1/cuentas/por-organo");
    // La grafía viaja tal cual: casarla con el órgano de la cuenta es del servidor.
    expect(query(baja.split(" ")[1]).get("organo")).toBe("AYUNTAMIENTO DE ALCALÁ");
    expect(query(baja.split(" ")[1]).get("organization_id")).toBe("21");
    expect(qc.getQueryData(clave)).toBeNull();
    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "dejar_de_seguir" });
  });

  it("si falla, el botón vuelve a marcarse", async () => {
    vi.stubGlobal(
      "fetch",
      servidor({
        "GET /api/v1/organizations": [[EQUIPO]],
        "DELETE /api/v1/cuentas/por-organo": [{ detail: "El rol viewer es de solo lectura." }, 403],
        "GET /api/v1/cuentas": [[ALCALA]],
      }),
    );
    const qc = crearCliente();
    const clave = cuentaKeys.deOrgano(21, "Ayuntamiento de Alcalá");
    qc.setQueryData(clave, ALCALA);

    const { result } = renderHook(() => useDejarDeSeguirOrgano(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync("Ayuntamiento de Alcalá").catch(() => undefined);
    });

    expect(qc.getQueryData(clave)).toEqual(ALCALA);
    expect(toast.error).toHaveBeenCalledWith("El rol viewer es de solo lectura.");
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});

describe("resumen, ficha y buscador", () => {
  it("el resumen y la ficha preguntan en la organización activa", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[PERSONAL, EQUIPO]],
      "GET /api/v1/cuentas/resumen": [{ filas: [] }],
      "GET /api/v1/cuentas/7": [{ cuenta: ALCALA }],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const resumen = renderHook(() => useCuentasResumen(), { wrapper: envoltorio(qc) });
    const ficha = renderHook(() => useFichaCuenta(7), { wrapper: envoltorio(qc) });
    await waitFor(() => expect(resumen.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(ficha.result.current.isSuccess).toBe(true));

    expect(pedidas(fetchMock).filter((p) => p.includes("/cuentas"))).toEqual(
      expect.arrayContaining([
        "GET /api/v1/cuentas/resumen?organization_id=21",
        "GET /api/v1/cuentas/7?organization_id=21",
      ]),
    );
  });

  it("la ficha sin id válido no pregunta", async () => {
    const fetchMock = servidor({ "GET /api/v1/organizations": [[EQUIPO]] });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    renderHook(() => useFichaCuenta(null), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);

    expect(pedidas(fetchMock).some((p) => p.includes("/cuentas"))).toBe(false);
  });

  it("el buscador no pregunta con menos de tres letras y luego sí, con el término", async () => {
    const candidato = {
      organo_nombre: "Pleno del Ayuntamiento de Soria",
      organo_norm: "pleno del ayuntamiento de soria",
      expedientes: 12,
      cuenta_id: null,
      cuenta_nombre: null,
    };
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "GET /api/v1/cuentas/buscar-organos": [[candidato]],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result, rerender } = renderHook(
      ({ termino }: { termino: string }) => useBuscarOrganos(termino),
      { wrapper: envoltorio(qc), initialProps: { termino: "so" } },
    );
    await organizacionResuelta(qc);
    expect(result.current.activa).toBe(false);
    expect(result.current.candidatos).toEqual([]);

    rerender({ termino: "soria" });
    await waitFor(() => expect(result.current.candidatos).toEqual([candidato]));

    const busquedas = pedidas(fetchMock).filter((p) => p.includes("buscar-organos"));
    expect(busquedas).toHaveLength(1);
    expect(query(busquedas[0].split(" ")[1]).get("q")).toBe("soria");
    expect(query(busquedas[0].split(" ")[1]).get("organization_id")).toBe("21");
  });
});

describe("useCrearCuenta y useRecuperarCuenta", () => {
  it("crea con varios órganos, sin mandar nombre ni nota vacíos, y mide el alta", async () => {
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "POST /api/v1/cuentas": [ALCALA, 201],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result } = renderHook(() => useCrearCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync({
        nombre: "   ",
        organos: ["Pleno", "Junta de Gobierno"],
        nota: "",
      });
    });

    const alta = fetchMock.mock.calls.find((c) => callMethod(c) === "POST");
    expect(callUrl(alta!)).toBe("/api/v1/cuentas?organization_id=21");
    // Un nombre en blanco no viaja: el servidor pone el del primer órgano.
    expect(JSON.parse(String((alta![1] as RequestInit).body))).toEqual({
      organos: ["Pleno", "Junta de Gobierno"],
    });
    expect(registrarEvento).toHaveBeenCalledWith("organo_seguido", { accion: "seguir" });
  });

  it("deshacer rehace la cuenta y le vuelve a poner sus etiquetas", async () => {
    const rehecha = { ...ALCALA, id: 9 };
    const fetchMock = servidor({
      "GET /api/v1/organizations": [[EQUIPO]],
      "POST /api/v1/cuentas": [rehecha, 201],
      "POST /api/v1/etiquetas/aplicar": [{ cambiado: true }, 200],
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = crearCliente();

    const { result } = renderHook(() => useRecuperarCuenta(), { wrapper: envoltorio(qc) });
    await organizacionResuelta(qc);
    await act(async () => {
      await result.current.mutateAsync({
        nombre: "Ayuntamiento de Alcalá",
        organos: ["Ayuntamiento de Alcalá"],
        nota: "Renueva en Q1",
        etiquetaIds: [3, 4],
      });
    });

    const escrituras = fetchMock.mock.calls.filter((c) => callMethod(c) === "POST");
    expect(escrituras.map((c) => callUrl(c).split("?")[0])).toEqual([
      "/api/v1/cuentas",
      "/api/v1/etiquetas/aplicar",
      "/api/v1/etiquetas/aplicar",
    ]);
    expect(JSON.parse(String((escrituras[0][1] as RequestInit).body))).toEqual({
      nombre: "Ayuntamiento de Alcalá",
      organos: ["Ayuntamiento de Alcalá"],
      nota: "Renueva en Q1",
    });
    // Las etiquetas van a la cuenta rehecha, que tiene otro id.
    expect(JSON.parse(String((escrituras[1][1] as RequestInit).body))).toEqual({
      etiqueta_id: 3,
      objeto_tipo: "cuenta",
      objeto_id: "9",
    });
  });
});
