/**
 * Ajustes: sesiones, claves y preferencias (C7.5, cliente de C2.1/C2.3/C2.7).
 *
 * El módulo entró con el espacio Ajustes y salió **sin un solo test**: 112
 * líneas al 0 %, que es lo que hundió el piso de cobertura de `src/hooks/**`
 * por debajo de su umbral en CI. No es un problema de porcentaje: son tres
 * superficies que el backend expuso justamente porque nadie las consumía —
 * `list_active_sessions` no tenía ruta, `api_key_tiers` no tenía lector y las
 * preferencias no tenían pantalla—, y su primer cliente no estaba probado.
 *
 * Lo que se fija aquí es lo que puede romperse sin que se note: la URL exacta
 * de cada llamada, el método, y que cada mutación invalide **su** clave de
 * caché. Una invalidación que apunte a la clave equivocada deja la pantalla
 * enseñando lo que acabás de borrar.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import {
  ajustesKeys,
  useClaves,
  useCrearClave,
  useGuardarPreferencias,
  usePreferencias,
  useRevocarSesion,
  useSesiones,
} from "@/hooks/use-ajustes";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** Un `QueryClient` estable por test (ver `use-meta-filters.test.tsx`). */
function crearEntorno() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}

function stub(body: unknown) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(body)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("useSesiones", () => {
  it("lee las sesiones abiertas del usuario", async () => {
    const fetchMock = stub({
      items: [{ id: "abc123", actual: true, ip: "1.2.3.4", user_agent: "Firefox" }],
    });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useSesiones(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(callUrl(fetchMock.mock.calls[0])).toContain("/api/v1/me/sessions");
    expect(result.current.data?.items?.[0]?.actual).toBe(true);
  });
});

describe("useRevocarSesion", () => {
  it("borra UNA sesión por su id público y refresca el listado", async () => {
    const fetchMock = stub({ status: "ok" });
    const { client, wrapper } = crearEntorno();
    const invalidar = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useRevocarSesion(), { wrapper });
    await result.current.mutateAsync("abc123");

    // El id va en la ruta y es el **hash público**, no el token: mandar el
    // token crudo lo dejaría en los logs del proxy y en el historial.
    expect(callUrl(fetchMock.mock.calls[0])).toContain("/api/v1/me/sessions/abc123");
    expect(callMethod(fetchMock.mock.calls[0])).toBe("DELETE");
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ajustesKeys.sesiones });
  });
});

describe("useClaves", () => {
  it("lee las claves con su tier", async () => {
    const fetchMock = stub({ items: [{ id: 1, name: "ci", tier: "standard", is_active: true }] });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useClaves(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(callUrl(fetchMock.mock.calls[0])).toContain("/api/v1/me/keys");
    // El `tier` es el motivo por el que esta ruta cambió de forma en C2.3: sin
    // él, el usuario no sabe con qué límite se le aplica su propia clave.
    expect(result.current.data?.items?.[0]?.tier).toBe("standard");
  });
});

describe("useCrearClave", () => {
  it("acuña la clave y refresca el listado, sin toast de éxito", async () => {
    const { toast } = await import("sonner");
    const fetchMock = stub({ id: 7, name: "ci", api_key: "tf_secreto" });
    const { client, wrapper } = crearEntorno();
    const invalidar = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCrearClave(), { wrapper });
    const creada = await result.current.mutateAsync({ name: "ci" });

    expect(callUrl(fetchMock.mock.calls[0])).toContain("/api/v1/me/keys");
    expect(callMethod(fetchMock.mock.calls[0])).toBe("POST");
    expect(creada.api_key).toBe("tf_secreto");
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ajustesKeys.claves });
    // El secreto no se puede volver a pedir, así que se enseña en un aviso que
    // no desaparece solo. Un toast efímero para un valor irrecuperable sería
    // una trampa, y por eso este camino NO lo emite.
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("avisa cuando la creación falla", async () => {
    const { toast } = await import("sonner");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.reject(new Error("403")))
    );
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useCrearClave(), { wrapper });
    await expect(result.current.mutateAsync({ name: "ci" })).rejects.toThrow();
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});

describe("preferencias de notificación", () => {
  it("lee las preferencias del usuario", async () => {
    const fetchMock = stub({ items: [{ tipo: "digest", canal: "email", frecuencia: "diaria" }] });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => usePreferencias(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(callUrl(fetchMock.mock.calls[0])).toContain("/api/v1/me/notification-preferences");
  });

  it("las guarda con PUT y refresca su propia clave", async () => {
    const fetchMock = stub({ status: "ok" });
    const { client, wrapper } = crearEntorno();
    const invalidar = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useGuardarPreferencias(), { wrapper });
    await result.current.mutateAsync([
      { tipo: "digest", canal: "email", frecuencia: "semanal" },
    ] as never);

    expect(callUrl(fetchMock.mock.calls[0])).toContain("/api/v1/me/notification-preferences");
    expect(callMethod(fetchMock.mock.calls[0])).toBe("PUT");
    // Su propia clave, no la de sesiones ni la de claves: invalidar la
    // equivocada deja la pantalla enseñando lo que acabás de cambiar.
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ajustesKeys.notificaciones });
  });

  it("avisa cuando el guardado falla", async () => {
    const { toast } = await import("sonner");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.reject(new Error("500")))
    );
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useGuardarPreferencias(), { wrapper });
    await expect(result.current.mutateAsync([] as never)).rejects.toThrow();
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
