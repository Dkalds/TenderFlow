/**
 * Política de reintentos y agrupación de avisos (`lib/query-feedback.ts`).
 *
 * El caso que motiva estos tests: la API corre en Render con spin-down, así que
 * el primer request tras un rato de inactividad tarda decenas de segundos. La
 * pantalla de Resumen dispara ~28 peticiones por carga; sin política de
 * reintentos y sin agrupación, eso eran ~28 toasts rojos idénticos, que se lee
 * como "la aplicación está rota" y no como "el servidor está despertando".
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  esErrorTransitorio,
  debeReintentar,
  retrasoDeReintento,
  notifyQueryError,
  reiniciarAgrupacionDeAvisos,
  MAX_REINTENTOS_TRANSITORIOS,
} from "@/lib/query-feedback";
import { ApiError } from "@/lib/api-client";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { toast } from "sonner";

/** El `Failed to fetch` que lanza el navegador cuando ni se conecta. */
function errorDeRed(): Error {
  return new TypeError("Failed to fetch");
}

describe("esErrorTransitorio", () => {
  it("considera transitorio un fallo de red del navegador", () => {
    expect(esErrorTransitorio(errorDeRed())).toBe(true);
    expect(esErrorTransitorio(new TypeError("Load failed"))).toBe(true);
    expect(esErrorTransitorio(new Error("NetworkError when attempting to fetch"))).toBe(true);
  });

  it("considera transitorio un 5xx y un 408 (arranque en frío / timeout)", () => {
    expect(esErrorTransitorio(new ApiError(500, "boom"))).toBe(true);
    expect(esErrorTransitorio(new ApiError(502, "bad gateway"))).toBe(true);
    expect(esErrorTransitorio(new ApiError(504, "gateway timeout"))).toBe(true);
    expect(esErrorTransitorio(new ApiError(408, "request timeout"))).toBe(true);
  });

  it("NO considera transitorio un 4xx de negocio", () => {
    expect(esErrorTransitorio(new ApiError(400, "bad request"))).toBe(false);
    expect(esErrorTransitorio(new ApiError(403, "forbidden"))).toBe(false);
    expect(esErrorTransitorio(new ApiError(404, "not found"))).toBe(false);
    expect(esErrorTransitorio(new ApiError(422, "unprocessable"))).toBe(false);
  });

  it("NO reintenta un 429: el rate-limit pide menos peticiones, no más", () => {
    expect(esErrorTransitorio(new ApiError(429, "too many requests"))).toBe(false);
  });

  it("NO considera transitoria una petición abortada ni un valor que no es Error", () => {
    const abortado = new Error("The operation was aborted");
    abortado.name = "AbortError";
    expect(esErrorTransitorio(abortado)).toBe(false);
    expect(esErrorTransitorio("cadena suelta")).toBe(false);
    expect(esErrorTransitorio(null)).toBe(false);
  });
});

describe("debeReintentar", () => {
  it("reintenta un fallo de red hasta el tope y ni una vez más", () => {
    // Los índices son los de query-core: `retry(failureCount, error)` se evalúa
    // ANTES del `failureCount++`, así que el primer fallo llega con 0. Iterar
    // desde 1 —como hacía este test— reproduce el modelo equivocado y deja
    // pasar un reintento de más sin que nada se ponga rojo.
    for (let fallos = 0; fallos < MAX_REINTENTOS_TRANSITORIOS; fallos++) {
      expect(debeReintentar(fallos, errorDeRed())).toBe(true);
    }
    expect(debeReintentar(MAX_REINTENTOS_TRANSITORIOS, errorDeRed())).toBe(false);
  });

  it("reintenta un 503 (instancia arrancando)", () => {
    expect(debeReintentar(1, new ApiError(503, "service unavailable"))).toBe(true);
  });

  it("NO reintenta un 400: la respuesta sería idéntica", () => {
    expect(debeReintentar(1, new ApiError(400, "bad request"))).toBe(false);
  });
});

describe("retrasoDeReintento", () => {
  it("crece exponencialmente desde 1s", () => {
    expect(retrasoDeReintento(0)).toBe(1000);
    expect(retrasoDeReintento(1)).toBe(2000);
    expect(retrasoDeReintento(2)).toBe(4000);
    expect(retrasoDeReintento(3)).toBe(8000);
  });

  it("está acotado: no espera más de 8s por intento", () => {
    expect(retrasoDeReintento(10)).toBe(8000);
  });

  it("el presupuesto total de espera se queda en el orden de un arranque en frío", () => {
    // Los índices que de verdad se piden son 0..MAX-1, los mismos con los que
    // `debeReintentar` dice que sí: 1s+2s+4s+8s. Si alguien vuelve a mover el
    // tope o el `<`, esta suma es lo que lo delata.
    const total = Array.from({ length: MAX_REINTENTOS_TRANSITORIOS }, (_, i) => retrasoDeReintento(i)).reduce(
      (a, b) => a + b,
      0,
    );
    expect(total).toBe(15_000);
    expect(total).toBeLessThanOrEqual(20_000);
    expect(total).toBeGreaterThanOrEqual(10_000);
  });
});

/** Opciones con las que se llamó a `toast.error` en la enésima invocación. */
function opcionesDelToast(indice: number): { id?: string; description?: string } {
  const mock = vi.mocked(toast.error);
  return (mock.mock.calls[indice]?.[1] ?? {}) as { id?: string; description?: string };
}

describe("agrupación de avisos", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reiniciarAgrupacionDeAvisos();
  });

  it("colapsa N fallos por la misma causa en un solo aviso", () => {
    // Las ~28 peticiones de la pantalla de Resumen cayendo por el mismo
    // arranque en frío.
    for (let i = 0; i < 28; i++) notifyQueryError(errorDeRed());

    const ids = new Set(vi.mocked(toast.error).mock.calls.map((_llamada, indice) => opcionesDelToast(indice).id));
    // Un único `id` de Sonner ⇒ un único toast visible, por muchas veces que se
    // actualice en sitio.
    expect(ids.size).toBe(1);
    expect(opcionesDelToast(27).description).toContain("28 peticiones afectadas");
  });

  it("un fallo aislado sigue avisando, sin recuento", () => {
    notifyQueryError(new ApiError(404, "No encontrado"));
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith("Error al cargar datos", expect.any(Object));
    expect(opcionesDelToast(0).description).toBe("No encontrado");
    expect(opcionesDelToast(0).description).not.toContain("peticiones afectadas");
  });

  it("dos causas distintas siguen siendo dos incidentes", () => {
    notifyQueryError(new ApiError(404, "No encontrado"));
    notifyQueryError(new ApiError(403, "Sin permiso"));
    expect(opcionesDelToast(0).id).not.toBe(opcionesDelToast(1).id);
  });

  it("el aviso de 'no responde' no promete que vaya a funcionar", () => {
    notifyQueryError(new ApiError(504, "gateway timeout"));
    expect(toast.error).toHaveBeenCalledWith("El servidor no responde", expect.any(Object));
    // Describe lo ya ocurrido (los reintentos se agotaron), no un futuro.
    expect(opcionesDelToast(0).description).toContain("tras varios reintentos");
  });

  it("sigue callando los 401: el redirect a login ya los resuelve", () => {
    notifyQueryError(new ApiError(401, "Unauthorized"));
    expect(toast.error).not.toHaveBeenCalled();
  });
});
