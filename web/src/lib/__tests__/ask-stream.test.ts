/**
 * Tests for src/lib/ask-stream.ts — SSE parsing of the full event contract:
 * {text}, fuentes_documentos, degraded, resumen_meta and [DONE].
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// La telemetría se dobla entera: aquí interesa *qué* evento sale de cada
// desenlace del stream, no que el SDK de analítica funcione.
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { registrarEvento } from "@/lib/analytics";
import { streamAsk, streamResumen } from "@/lib/ask-stream";

/** Build a Response whose body streams the given SSE lines. */
function sseResponse(lines: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const line of lines) controller.enqueue(encoder.encode(line));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  // jsdom starts with document.cookie = "" — reset via defineProperty trick
  // so csrf_token set by one test doesn't leak into the next.
  Object.defineProperty(document, "cookie", {
    writable: true,
    configurable: true,
    value: "",
  });
  vi.mocked(registrarEvento).mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamAsk", () => {
  it("accumulates text events and stops at [DONE]", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'data: {"text": "Hola "}\n\n',
            'data: {"text": "mundo"}\n\n',
            "data: [DONE]\n\n",
            'data: {"text": "no debería llegar"}\n\n',
          ]),
        ),
    );

    const tokens: string[] = [];
    const result = await streamAsk({
      question: "saluda",
      onToken: (acc) => tokens.push(acc),
    });

    expect(result.answer).toBe("Hola mundo");
    expect(tokens).toEqual(["Hola ", "Hola mundo"]);
    expect(result.fuentes).toEqual([]);
    expect(result.degraded).toBeNull();
  });

  it("parses fuentes_documentos and exposes them via callback and result", async () => {
    const fuentes = [
      {
        id_externo: "EXP-1",
        titulo: "T",
        chunks: [{ chunk_index: 0, texto: "frag", tipo: "legal", filename: "PCAP.pdf" }],
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            `data: ${JSON.stringify({ fuentes_documentos: fuentes })}\n\n`,
            'data: {"text": "respuesta"}\n\n',
            "data: [DONE]\n\n",
          ]),
        ),
    );

    const onFuentes = vi.fn();
    const result = await streamAsk({ question: "q", onToken: vi.fn(), onFuentes });

    expect(result.fuentes).toEqual(fuentes);
    expect(onFuentes).toHaveBeenCalledWith(fuentes);
    expect(result.answer).toBe("respuesta");
  });

  it("parses the degraded event with reason and docs", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'data: {"degraded": true, "reason": "provider_error", "docs": [{"id_externo": "L1"}]}\n\n',
            "data: [DONE]\n\n",
          ]),
        ),
    );

    const onDegraded = vi.fn();
    const result = await streamAsk({ question: "q", onToken: vi.fn(), onDegraded });

    expect(result.degraded).toEqual({
      reason: "provider_error",
      docs: [{ id_externo: "L1" }],
    });
    expect(onDegraded).toHaveBeenCalledOnce();
    expect(result.answer).toBe("");
  });

  it("sends messages and id_externo in the request body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await streamAsk({
      question: "¿y el plazo?",
      messages: [
        { role: "user", content: "primera" },
        { role: "assistant", content: "respuesta" },
      ],
      idExterno: "EXP-1",
      onToken: vi.fn(),
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.messages).toEqual([
      { role: "user", content: "primera" },
      { role: "assistant", content: "respuesta" },
    ]);
    expect(body.id_externo).toBe("EXP-1");
    expect(body.question).toBe("¿y el plazo?");
  });

  it("omits messages and id_externo when not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await streamAsk({ question: "hola mundo", onToken: vi.fn() });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).not.toHaveProperty("messages");
    expect(body).not.toHaveProperty("id_externo");
  });

  it("falls back to plain JSON responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ answer: "plano" })));

    const result = await streamAsk({ question: "q", onToken: vi.fn() });
    expect(result.answer).toBe("plano");
  });

  it("throws on non-OK responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 429 })));

    await expect(streamAsk({ question: "q", onToken: vi.fn() })).rejects.toThrow("Error 429");
  });

  it("includes X-CSRF-Token header when csrf_token cookie is present", async () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "csrf_token=mytoken",
    });
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await streamAsk({ question: "q", onToken: vi.fn() });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("mytoken");
  });
});

describe("streamResumen", () => {
  it("POSTs to the resumen endpoint and parses resumen_meta first", async () => {
    const meta = {
      has_pliego_text: false,
      truncated: false,
      documentos: [{ tipo: "legal", filename: "PCAP.pdf", status: "pending" }],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        sseResponse([
          `data: ${JSON.stringify({ resumen_meta: meta })}\n\n`,
          'data: {"text": "## Qué se licita"}\n\n',
          "data: [DONE]\n\n",
        ]),
      );
    vi.stubGlobal("fetch", fetchMock);

    const onResumenMeta = vi.fn();
    const result = await streamResumen({
      idExterno: "EXP-1",
      onToken: vi.fn(),
      onResumenMeta,
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/licitaciones/EXP-1/resumen");
    expect(result.resumenMeta).toEqual(meta);
    expect(onResumenMeta).toHaveBeenCalledWith(meta);
    expect(result.answer).toBe("## Qué se licita");
  });

  it("encodes the id_externo in the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await streamResumen({ idExterno: "EXP/RARO 1", onToken: vi.fn() });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/licitaciones/EXP%2FRARO%201/resumen");
  });

  it("includes X-CSRF-Token header when csrf_token cookie is present", async () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "csrf_token=mytoken",
    });
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await streamResumen({ idExterno: "EXP-1", onToken: vi.fn() });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("mytoken");
  });
});

/* ── Stream que se corta a media respuesta ──────────────────────────────── */

/**
 * Response SSE que emite los chunks dados y luego rompe el cuerpo.
 *
 * Va por `pull` y no por `start`: romper el stream dentro de `start` descarta
 * lo ya encolado y el cliente no llega a leer nada, que es justo el escenario
 * contrario al que interesa aquí (leer media respuesta y perder el resto).
 */
function sseAbortadoTras(chunks: string[], error: Error): Response {
  const encoder = new TextEncoder();
  let emitidos = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (emitidos < chunks.length) {
        controller.enqueue(encoder.encode(chunks[emitidos]));
        emitidos += 1;
        return;
      }
      controller.error(error);
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

describe("stream interrumpido", () => {
  it("una caída de red a media respuesta rechaza en vez de devolver media respuesta", async () => {
    // La distinción que sostiene el producto: `streamAsk` resuelve = la
    // respuesta terminó. Si el cuerpo se rompe y aun así resolviera, quien
    // llama no tiene forma de saber que lo que pinta está a medias, y la
    // burbuja se queda con media frase presentada como respuesta completa.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseAbortadoTras(
            ['data: {"text": "El plazo de presentación termina el"}\n\n'],
            new Error("network error"),
          ),
        ),
    );

    const tokens: string[] = [];
    await expect(
      streamAsk({ question: "¿plazo?", onToken: (acc) => tokens.push(acc) }),
    ).rejects.toThrow();

    // El texto llegó a pintarse —eso es el streaming— pero la promesa no
    // resolvió: el estado "terminado" nunca se alcanza.
    expect(tokens).toEqual(["El plazo de presentación termina el"]);
  });

  it("un corte de red no cuenta como uso del asistente", async () => {
    // Ni "ok" ni "error": el asistente no falló, se cayó el enlace. Contarlo
    // como error ensuciaría la única métrica que dice si esto sirve.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseAbortadoTras([], new Error("network error"))),
    );

    await expect(streamAsk({ question: "q", onToken: vi.fn() })).rejects.toThrow();
    expect(registrarEvento).not.toHaveBeenCalled();
  });

  it("un abort del usuario tampoco emite telemetría", async () => {
    const abortError = new DOMException("The user aborted a request.", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));

    await expect(streamAsk({ question: "q", onToken: vi.fn() })).rejects.toThrow(
      "The user aborted a request.",
    );
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});

/* ── Telemetría del desenlace ───────────────────────────────────────────── */

describe("telemetría asistente_usado", () => {
  it("una respuesta con síntesis cuenta como uso que sirvió", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse(['data: {"text": "ok"}\n\n', "data: [DONE]\n\n"])),
    );

    await streamAsk({ question: "q", onToken: vi.fn() });

    expect(registrarEvento).toHaveBeenCalledWith("asistente_usado", {
      modo: "pregunta",
      ambito: "corpus",
      resultado: "ok",
    });
  });

  it("`degraded` se propaga al evento: uso que NO sirvió", async () => {
    // Es el evento que emite el backend cuando el proveedor LLM falla o se
    // agota el presupuesto. Si se contara como "ok", el asistente aparentaría
    // funcionar mientras devuelve documentos sin síntesis.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'data: {"degraded": true, "reason": "presupuesto_agotado", "docs": []}\n\n',
            "data: [DONE]\n\n",
          ]),
        ),
    );

    const onDegraded = vi.fn();
    const result = await streamAsk({ question: "q", onToken: vi.fn(), onDegraded });

    expect(onDegraded).toHaveBeenCalledWith({ reason: "presupuesto_agotado", docs: [] });
    expect(result.degraded?.reason).toBe("presupuesto_agotado");
    expect(registrarEvento).toHaveBeenCalledWith("asistente_usado", {
      modo: "pregunta",
      ambito: "corpus",
      resultado: "degradado",
    });
  });

  it("preguntar sobre una licitación se distingue de preguntar al corpus", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"])));

    await streamAsk({ question: "q", idExterno: "EXP-1", onToken: vi.fn() });

    expect(registrarEvento).toHaveBeenCalledWith(
      "asistente_usado",
      expect.objectContaining({ ambito: "licitacion" }),
    );
  });

  it("un rechazo del servidor sí cuenta como error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 429 })));

    await expect(streamAsk({ question: "q", onToken: vi.fn() })).rejects.toThrow("Error 429");
    expect(registrarEvento).toHaveBeenCalledWith("asistente_usado", {
      modo: "pregunta",
      ambito: "corpus",
      resultado: "error",
    });
  });

  it("el resumen degradado se distingue del resumen con síntesis", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'data: {"degraded": true, "reason": "sin_pliego"}\n\n',
            "data: [DONE]\n\n",
          ]),
        ),
    );

    await streamResumen({ idExterno: "EXP-1", onToken: vi.fn() });

    expect(registrarEvento).toHaveBeenCalledWith("asistente_usado", {
      modo: "resumen",
      ambito: "licitacion",
      resultado: "degradado",
    });
  });

  it("la pregunta y la licitación NUNCA viajan en el evento", async () => {
    // Regla de privacidad de `lib/analytics.ts`: el `id_externo` identifica la
    // licitación y con ella el negocio del cliente.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(["data: [DONE]\n\n"])));

    await streamAsk({
      question: "¿cuánto paga el Ayuntamiento de X?",
      idExterno: "EXP-SECRETO",
      onToken: vi.fn(),
    });

    const [, propiedades] = vi.mocked(registrarEvento).mock.calls[0];
    expect(Object.keys(propiedades)).toEqual(["modo", "ambito", "resultado"]);
    expect(JSON.stringify(propiedades)).not.toContain("EXP-SECRETO");
  });
});

/* ── ask_meta (ámbito efectivo) y caché del resumen ─────────────────────── */

describe("ask_meta y resumen cacheado", () => {
  it("parses ask_meta and exposes the effective scope", async () => {
    // Con id_externo pedido pero contexto caído, el backend degrada al corpus
    // y lo declara en ask_meta: la UI avisa en vez de fingir contexto.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'data: {"ask_meta": {"contexto": "general", "id_externo": "EXP-1"}}\n\n',
            'data: {"text": "respuesta"}\n\n',
            "data: [DONE]\n\n",
          ]),
        ),
    );

    const onAskMeta = vi.fn();
    const result = await streamAsk({
      question: "q",
      idExterno: "EXP-1",
      onToken: vi.fn(),
      onAskMeta,
    });

    expect(result.askMeta).toEqual({ contexto: "general", id_externo: "EXP-1" });
    expect(onAskMeta).toHaveBeenCalledWith({ contexto: "general", id_externo: "EXP-1" });
  });

  it("resumen_meta.cached llega al resultado", async () => {
    const meta = { has_pliego_text: true, truncated: false, cached: true, documentos: [] };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            `data: ${JSON.stringify({ resumen_meta: meta })}\n\n`,
            'data: {"text": "resumen guardado"}\n\n',
            "data: [DONE]\n\n",
          ]),
        ),
    );

    const result = await streamResumen({ idExterno: "EXP-1", onToken: vi.fn() });
    expect(result.resumenMeta?.cached).toBe(true);
  });

  it("force viaja en el body del resumen (y se omite por defecto)", async () => {
    // Una Response nueva por llamada: el body de una Response solo puede leerse
    // una vez, y aquí el mock atiende dos peticiones.
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(sseResponse(["data: [DONE]\n\n"])),
    );
    vi.stubGlobal("fetch", fetchMock);

    await streamResumen({ idExterno: "EXP-1", onToken: vi.fn() });
    await streamResumen({ idExterno: "EXP-1", force: true, onToken: vi.fn() });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).not.toHaveProperty("force");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).force).toBe(true);
  });
});
