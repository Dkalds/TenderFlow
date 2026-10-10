import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `instrumentation-client` pide el SDK de Sentry aparte y, mientras llega,
 * guarda en una cola lo que falla. Aquí se prueba esa ventana con un doble de
 * `lib/sentry-cliente`: el SDK de verdad no se carga.
 *
 * El módulo actúa al importarse y lee el DSN al cargar, así que cada caso
 * reinicia los módulos y lo importa de nuevo con su entorno.
 */
const doble = {
  arrancarSentry: vi.fn(),
  capturarNoManejado: vi.fn(),
  sumideroSentry: vi.fn(),
};

/**
 * Importa el módulo con el SDK retenido tras una puerta: `llegaElSdk()` la abre
 * y espera a que arranque. Así cada caso decide qué pasa antes y qué después.
 */
async function cargar() {
  let abrir!: () => void;
  const puerta = new Promise<void>((resolver) => (abrir = resolver));
  vi.doMock("@/lib/sentry-cliente", async () => {
    await puerta;
    return doble;
  });
  await import("@/instrumentation-client");
  const { reportError } = await import("@/lib/report-error");
  const llegaElSdk = async () => {
    abrir();
    await vi.waitFor(() => expect(doble.arrancarSentry).toHaveBeenCalled());
  };
  return { reportError, llegaElSdk };
}

/**
 * Con su propio oyente mientras dura el envío: vitest da por no capturado un
 * `error` que llega a un `window` sin nadie escuchando, y aquí hay casos que
 * comprueban justo eso, que el módulo ya no escucha.
 */
function errorEnWindow(error: Error) {
  const testigo = () => {};
  window.addEventListener("error", testigo);
  window.dispatchEvent(new ErrorEvent("error", { error, message: error.message }));
  window.removeEventListener("error", testigo);
}

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.spyOn(console, "debug").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true })),
  );
});

afterEach(() => {
  vi.doUnmock("@/lib/sentry-cliente");
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("sin DSN", () => {
  it("ni pide el SDK ni conecta nada", async () => {
    const importado = vi.fn(() => doble);
    vi.doMock("@/lib/sentry-cliente", importado);
    await import("@/instrumentation-client");
    const { reportError } = await import("@/lib/report-error");
    vi.stubEnv("NODE_ENV", "production");

    errorEnWindow(new Error("boom"));
    reportError("Ctx", new Error("boom"));
    await new Promise((r) => setTimeout(r, 20));

    expect(importado).not.toHaveBeenCalled();

    expect(doble.arrancarSentry).not.toHaveBeenCalled();
    expect(doble.capturarNoManejado).not.toHaveBeenCalled();
    expect(doble.sumideroSentry).not.toHaveBeenCalled();
  });
});

describe("con DSN", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "https://clave@o1.ingest.de.sentry.io/2");
  });

  it("entrega al SDK lo que falló antes de que llegara", async () => {
    const { reportError, llegaElSdk } = await cargar();
    vi.stubEnv("NODE_ENV", "production");
    const temprano = new Error("falló hidratando");
    errorEnWindow(temprano);
    const rechazo = new Error("promesa sin catch");
    window.dispatchEvent(Object.assign(new Event("unhandledrejection"), { reason: rechazo }));
    const reportado = new Error("lo atrapó un error.tsx");
    reportError("DashboardError", reportado);
    expect(doble.arrancarSentry).not.toHaveBeenCalled();

    await llegaElSdk();
    expect(doble.capturarNoManejado.mock.calls).toEqual([[temprano], [rechazo]]);
    expect(doble.sumideroSentry).toHaveBeenCalledExactlyOnceWith(reportado, {
      contexto: "DashboardError",
      origen: "manual",
    });
  });

  it("una vez arrancado deja de escuchar: lo de `window` ya es cosa del SDK", async () => {
    const { llegaElSdk } = await cargar();
    await llegaElSdk();

    errorEnWindow(new Error("después"));
    expect(doble.capturarNoManejado).not.toHaveBeenCalled();
  });

  it("una vez arrancado, lo que pasa por reportError va directo al SDK", async () => {
    const { reportError, llegaElSdk } = await cargar();
    await llegaElSdk();
    vi.stubEnv("NODE_ENV", "production");

    const err = new Error("boom");
    reportError("Ctx", err);
    expect(doble.sumideroSentry).toHaveBeenCalledExactlyOnceWith(err, { contexto: "Ctx", origen: "manual" });
  });

  it("la cola tiene tope", async () => {
    const { llegaElSdk } = await cargar();
    for (let i = 0; i < 50; i += 1) errorEnWindow(new Error(`vuelta ${i}`));
    await llegaElSdk();
    expect(doble.capturarNoManejado).toHaveBeenCalledTimes(10);
  });

  it("si el chunk no llega, suelta la cola y el canal propio sigue reportando", async () => {
    vi.doMock("@/lib/sentry-cliente", () => {
      throw new Error("chunk bloqueado");
    });
    const quitar = vi.spyOn(window, "removeEventListener");
    await import("@/instrumentation-client");
    const { reportError } = await import("@/lib/report-error");
    await vi.waitFor(() => expect(quitar).toHaveBeenCalledWith("error", expect.any(Function)));
    vi.stubEnv("NODE_ENV", "production");

    expect(() => reportError("Ctx", new Error("boom"))).not.toThrow();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(doble.sumideroSentry).not.toHaveBeenCalled();
  });
});
