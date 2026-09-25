/**
 * Cadencia de entrega de `onToken` en `src/lib/ask-stream.ts`.
 *
 * Cada `onToken` acaba en un `setState` que repinta el hilo, y un modelo
 * rápido emite varios tokens por frame: se entregan como mucho una vez por
 * frame, con el acumulado. Se fija aquí con un `requestAnimationFrame` que el
 * test controla y un cuerpo SSE al que se empuja texto cuando interesa — con
 * el cuerpo entero encolado de antemano (lo que hacen los otros dos ficheros)
 * todo cae en el mismo frame y no se ve la cadencia.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { streamAsk } from "@/lib/ask-stream";

/** `requestAnimationFrame` manual: los frames solo se pintan con `pintarFrame`. */
function framesManuales() {
  const pendientes = new Map<number, FrameRequestCallback>();
  let siguiente = 1;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    const id = siguiente++;
    pendientes.set(id, cb);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    pendientes.delete(id);
  });
  return {
    pendientes: () => pendientes.size,
    pintarFrame: () => {
      const lote = [...pendientes.values()];
      pendientes.clear();
      for (const cb of lote) cb(performance.now());
    },
  };
}

/** Cuerpo SSE al que el test empuja líneas cuando quiere. */
function sseManual() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    emitir: (linea: string) => controller.enqueue(encoder.encode(linea)),
    romper: (error: unknown) => controller.error(error),
  };
}

/** Deja que el lector consuma lo encolado (todo son microtareas). */
const leido = () => new Promise((resolve) => setTimeout(resolve, 0));

let frames: ReturnType<typeof framesManuales>;

beforeEach(() => {
  frames = framesManuales();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("onToken por frame", () => {
  it("agrupa los tokens de un mismo frame y entrega el acumulado", async () => {
    const sse = sseManual();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse.response));
    const tokens: string[] = [];
    const respuesta = streamAsk({ question: "q", onToken: (acc) => tokens.push(acc) });

    sse.emitir('data: {"text": "Ho"}\n');
    sse.emitir('data: {"text": "la"}\n');
    await leido();
    // Llegó texto, pero hasta que no se pinta el frame no se entrega nada.
    expect(tokens).toEqual([]);
    expect(frames.pendientes()).toBe(1);

    frames.pintarFrame();
    expect(tokens).toEqual(["Hola"]);

    sse.emitir('data: {"text": " mun"}\n');
    await leido();
    frames.pintarFrame();
    expect(tokens).toEqual(["Hola", "Hola mun"]);

    // Lo pendiente al cerrar sale sin esperar al frame, y el frame programado
    // se cancela: nada se entrega después de que la promesa resuelva.
    sse.emitir('data: {"text": "do"}\n');
    sse.emitir("data: [DONE]\n");
    const resultado = await respuesta;
    expect(resultado.answer).toBe("Hola mundo");
    expect(tokens).toEqual(["Hola", "Hola mun", "Hola mundo"]);
    expect(frames.pendientes()).toBe(0);
  });

  it("un evento de metadatos sale después del texto que lo precedía", async () => {
    const sse = sseManual();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse.response));
    const orden: string[] = [];
    const respuesta = streamAsk({
      question: "q",
      onToken: (acc) => orden.push(`texto:${acc}`),
      onFuentes: () => orden.push("fuentes"),
    });

    sse.emitir('data: {"text": "respuesta"}\n');
    sse.emitir(`data: ${JSON.stringify({ fuentes_documentos: [] })}\n`);
    sse.emitir("data: [DONE]\n");
    await respuesta;

    expect(orden).toEqual(["texto:respuesta", "fuentes"]);
  });

  it("tras un abort no se entrega el texto pendiente, ni aunque el frame llegue a pintarse", async () => {
    const sse = sseManual();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse.response));
    const abort = new AbortController();
    const tokens: string[] = [];
    const respuesta = streamAsk({ question: "q", signal: abort.signal, onToken: (acc) => tokens.push(acc) });

    sse.emitir('data: {"text": "texto viejo"}\n');
    await leido();
    abort.abort();
    // El frame puede pintarse antes de que el lector se entere del abort.
    frames.pintarFrame();
    expect(tokens).toEqual([]);

    sse.romper(new DOMException("The user aborted a request.", "AbortError"));
    await expect(respuesta).rejects.toThrow("The user aborted a request.");
    expect(tokens).toEqual([]);
    expect(frames.pendientes()).toBe(0);
  });

  it("un corte de red entrega lo que ya había llegado antes de rechazar", async () => {
    const sse = sseManual();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse.response));
    const tokens: string[] = [];
    const respuesta = streamAsk({ question: "q", onToken: (acc) => tokens.push(acc) });

    sse.emitir('data: {"text": "El plazo termina el"}\n');
    await leido();
    sse.romper(new Error("network error"));

    await expect(respuesta).rejects.toThrow("network error");
    expect(tokens).toEqual(["El plazo termina el"]);
    expect(frames.pendientes()).toBe(0);
  });
});
