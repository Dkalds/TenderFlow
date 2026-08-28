import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { reportError, reiniciarReporteErrores } from "@/lib/report-error";

const ENDPOINT = "/api/v1/security/client-error";

/** Lee el JSON que se envió por la llamada `n` del doble de `fetch`. */
function cuerpoEnviado(fetchMock: ReturnType<typeof vi.fn>, n = 0): Record<string, unknown> {
  const init = fetchMock.mock.calls[n]?.[1] as RequestInit;
  return JSON.parse(String(init.body)) as Record<string, unknown>;
}

describe("reportError", () => {
  let consoleSpy: ReturnType<typeof vi.spyOn>;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    reiniciarReporteErrores();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("logs to console.error in development with an Error instance", () => {
    vi.stubEnv("NODE_ENV", "development");
    const err = new Error("test error");
    reportError("MyContext", err);
    expect(consoleSpy).toHaveBeenCalledWith("[MyContext]", "test error", "");
  });

  it("logs to console.error in development with a string error", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", "something went wrong");
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "something went wrong", "");
  });

  it("logs 'Unknown error' for non-string, non-Error values", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", 42);
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "Unknown error", "");
  });

  it("logs 'Unknown error' for object error values", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", { code: 500 });
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "Unknown error", "");
  });

  it("passes extra data to console.error", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", "msg", { userId: "123" });
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "msg", { userId: "123" });
  });

  it("logs stack trace to console.debug when error has a stack", () => {
    vi.stubEnv("NODE_ENV", "development");
    const err = new Error("stack test");
    reportError("Ctx", err);
    expect(debugSpy).toHaveBeenCalledWith(err.stack);
  });

  it("does not log stack when error has no stack", () => {
    vi.stubEnv("NODE_ENV", "development");
    const err = new Error("no stack");
    err.stack = undefined;
    reportError("Ctx", err);
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("does not call console.error outside of development", () => {
    // NODE_ENV is "test" by default in vitest
    reportError("Ctx", new Error("prod error"));
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("still logs the stack in any env when error has a stack", () => {
    // debug runs regardless of NODE_ENV when error.stack is present
    const err = new Error("always debug");
    reportError("Ctx", err);
    expect(debugSpy).toHaveBeenCalledWith(err.stack);
  });
});

/**
 * El canal remoto. Se ejercita con `NODE_ENV` stubeado a "production" porque en
 * el entorno de test el reporter no hace red a propósito (ver el comentario del
 * módulo): sin ese stub, cada test unitario del repo que provoque un error
 * intentaría abrir una conexión.
 */
describe("reportError · envío al backend", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.spyOn(console, "debug").mockImplementation(() => {});
    reiniciarReporteErrores();
    vi.stubEnv("NODE_ENV", "production");
    // Sin `sendBeacon` definido, jsdom deja el respaldo `fetch` como camino
    // activo, que es el que permite leer el cuerpo como texto plano.
    fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("no envía nada en el entorno de test", () => {
    vi.stubEnv("NODE_ENV", "test");
    reportError("Ctx", new Error("boom"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("postea el error al endpoint propio del mismo origen", () => {
    reportError("Ctx", new Error("boom"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(ENDPOINT);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.keepalive).toBe(true);
    // Sin cookie de sesión: el endpoint no la necesita ni la mira.
    expect(init.credentials).toBe("omit");
  });

  it("envía mensaje, origen, contexto y stack", () => {
    const err = new Error("algo reventó");
    reportError("ConsoleRail.logout", err, undefined, "onerror");
    const cuerpo = cuerpoEnviado(fetchMock);
    expect(cuerpo.message).toBe("algo reventó");
    expect(cuerpo.source).toBe("onerror");
    expect(cuerpo.context).toBe("ConsoleRail.logout");
    expect(String(cuerpo.stack).length).toBeGreaterThan(0);
  });

  it("adjunta el digest de Next cuando el error lo trae", () => {
    const err = Object.assign(new Error("fallo de servidor"), { digest: "1a2b3c" });
    reportError("global-error", err, undefined, "global-error");
    expect(cuerpoEnviado(fetchMock).digest).toBe("1a2b3c");
  });

  it("nunca envía el `extra` del call-site", () => {
    reportError("Ctx", new Error("boom"), {
      email: "persona@example.com",
      formulario: { nif: "B12345678" }, // pragma: allowlist secret — NIF ficticio: se comprueba que NO viaja
    });
    const crudo = String((fetchMock.mock.calls[0]?.[1] as RequestInit).body);
    expect(crudo).not.toContain("persona@example.com");
    expect(crudo).not.toContain("B12345678"); // pragma: allowlist secret
    expect(cuerpoEnviado(fetchMock)).not.toHaveProperty("extra");
  });

  it("envía el pathname pero nunca la query string", () => {
    window.history.replaceState({}, "", "/mercado?tecnologia=SAP&empresa=Acme");
    reportError("Ctx", new Error("boom"));
    const crudo = String((fetchMock.mock.calls[0]?.[1] as RequestInit).body);
    expect(cuerpoEnviado(fetchMock).path).toBe("/mercado");
    expect(crudo).not.toContain("SAP");
    expect(crudo).not.toContain("Acme");
    window.history.replaceState({}, "", "/");
  });

  it("deduplica el mismo error repetido", () => {
    for (let i = 0; i < 500; i += 1) {
      reportError("Ctx", new Error("el mismo de siempre"));
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("distingue errores distintos aunque compartan contexto", () => {
    reportError("Ctx", new Error("uno"));
    reportError("Ctx", new Error("dos"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("distingue el mismo mensaje bajo orígenes distintos", () => {
    reportError("Ctx", new Error("igual"), undefined, "onerror");
    reportError("Ctx", new Error("igual"), undefined, "unhandledrejection");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("corta en el presupuesto de la ventana aunque los mensajes sean todos distintos", () => {
    // El caso que la deduplicación no cubre: un bucle que genera un mensaje
    // nuevo en cada vuelta, así que la huella nunca se repite.
    for (let i = 0; i < 50; i += 1) {
      reportError("Ctx", new Error(`fallo número ${i}`));
    }
    expect(fetchMock).toHaveBeenCalledTimes(8);
  });

  it("recupera presupuesto al pasar la ventana de envíos", () => {
    vi.useFakeTimers();
    try {
      for (let i = 0; i < 50; i += 1) {
        reportError("Ctx", new Error(`fallo número ${i}`));
      }
      expect(fetchMock).toHaveBeenCalledTimes(8);
      // Una SPA vive horas: el presupuesto es deslizante, no "por carga".
      vi.advanceTimersByTime(61_000);
      reportError("Ctx", new Error("un rato después"));
      expect(fetchMock).toHaveBeenCalledTimes(9);
    } finally {
      vi.useRealTimers();
    }
  });

  it("vuelve a reportar la misma huella pasada la ventana de deduplicación", () => {
    vi.useFakeTimers();
    try {
      reportError("Ctx", new Error("crónico"));
      vi.advanceTimersByTime(30_000);
      reportError("Ctx", new Error("crónico"));
      expect(fetchMock).toHaveBeenCalledTimes(1);
      vi.advanceTimersByTime(6 * 60_000);
      reportError("Ctx", new Error("crónico"));
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("recorta mensaje y stack antes de enviarlos", () => {
    const err = new Error("x".repeat(5000));
    err.stack = "y".repeat(50_000);
    reportError("Ctx", err);
    const cuerpo = cuerpoEnviado(fetchMock);
    expect(String(cuerpo.message)).toHaveLength(300);
    expect(String(cuerpo.stack)).toHaveLength(2000);
  });

  it("prefiere sendBeacon cuando existe", () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(window.navigator, "sendBeacon", {
      value: beacon,
      configurable: true,
      writable: true,
    });
    try {
      reportError("Ctx", new Error("boom"));
      expect(beacon).toHaveBeenCalledTimes(1);
      expect(beacon).toHaveBeenCalledWith(ENDPOINT, expect.any(Blob));
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      Reflect.deleteProperty(window.navigator, "sendBeacon");
    }
  });

  it("cae a fetch cuando sendBeacon rechaza el envío", () => {
    // `sendBeacon` devuelve false cuando la cola del navegador está llena.
    Object.defineProperty(window.navigator, "sendBeacon", {
      value: vi.fn(() => false),
      configurable: true,
      writable: true,
    });
    try {
      reportError("Ctx", new Error("boom"));
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      Reflect.deleteProperty(window.navigator, "sendBeacon");
    }
  });

  it("no lanza si sendBeacon lanza", () => {
    Object.defineProperty(window.navigator, "sendBeacon", {
      value: vi.fn(() => {
        throw new Error("cuota de beacons agotada");
      }),
      configurable: true,
      writable: true,
    });
    try {
      expect(() => reportError("Ctx", new Error("boom"))).not.toThrow();
      // Y sigue intentando el respaldo.
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      Reflect.deleteProperty(window.navigator, "sendBeacon");
    }
  });

  it("no lanza si fetch lanza de forma síncrona", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new Error("sin red");
      }),
    );
    expect(() => reportError("Ctx", new Error("boom"))).not.toThrow();
  });

  it("no deja una promesa rechazada sin manejar cuando fetch falla", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("429"))),
    );
    const alRechazo = vi.fn();
    window.addEventListener("unhandledrejection", alRechazo);
    try {
      expect(() => reportError("Ctx", new Error("boom"))).not.toThrow();
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(alRechazo).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("unhandledrejection", alRechazo);
    }
  });

  it("no lanza aunque console.error reviente", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.spyOn(console, "error").mockImplementation(() => {
      throw new Error("consola rota");
    });
    expect(() => reportError("Ctx", new Error("boom"))).not.toThrow();
  });

  it("no lanza con un error que no es Error ni string", () => {
    expect(() => reportError("Ctx", Symbol("raro"))).not.toThrow();
    expect(cuerpoEnviado(fetchMock).message).toBe("Unknown error");
  });

  it("reiniciarReporteErrores permite volver a enviar la misma huella", () => {
    reportError("Ctx", new Error("repetido"));
    reportError("Ctx", new Error("repetido"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    reiniciarReporteErrores();
    reportError("Ctx", new Error("repetido"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
