/**
 * Tests del *framing* SSE de `src/lib/ask-stream.ts`.
 *
 * `ask-stream.test.ts` cubre el contrato de eventos (text, fuentes_documentos,
 * degraded, resumen_meta, [DONE]). Aquí van los caminos que dependen de **cómo
 * llegan los bytes**, no de qué dicen: un token partido entre dos chunks de red,
 * una línea que no es JSON, líneas sueltas sin el prefijo `data: `. Son los que
 * fallan en producción con un modelo que emite rápido y nunca en un test que
 * manda cada evento en su propio chunk.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { streamAsk, streamResumen } from "@/lib/ask-stream";

/** Response SSE cuyo cuerpo emite exactamente los chunks dados. */
function sseChunks(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("framing SSE", () => {
  it("reensambla un evento partido entre dos chunks de red", async () => {
    // El troceado de la red no respeta los límites de línea: la mitad de un
    // JSON puede llegar en el siguiente `read()`.
    stubFetch(sseChunks(['data: {"text": "Ho', 'la mundo"}\n\n']));

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.answer).toBe("Hola mundo");
  });

  it("procesa varios eventos que llegan en un solo chunk", async () => {
    stubFetch(sseChunks(['data: {"text": "a"}\ndata: {"text": "b"}\ndata: {"text": "c"}\n']));

    const tokens: string[] = [];
    const result = await streamAsk({ question: "q", onToken: (acc) => tokens.push(acc) });
    expect(result.answer).toBe("abc");
    expect(tokens).toEqual(["a", "ab", "abc"]);
  });

  it("una línea SSE que no es JSON se acumula como texto crudo", async () => {
    // Algunos proveedores emiten texto plano si el modelo se cae a un fallback:
    // vale más enseñarlo que descartarlo en silencio.
    stubFetch(sseChunks(["data: texto sin json\n\n"]));

    const tokens: string[] = [];
    const result = await streamAsk({ question: "q", onToken: (acc) => tokens.push(acc) });
    expect(result.answer).toBe("texto sin json");
    expect(tokens).toEqual(["texto sin json"]);
  });

  it("ignora líneas vacías y las que no llevan el prefijo `data: `", async () => {
    stubFetch(
      sseChunks([
        "\n",
        ": heartbeat\n",
        "event: message\n",
        'data: {"text": "ok"}\n\n',
      ]),
    );

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.answer).toBe("ok");
  });

  it("un evento sin `text` no dispara onToken", async () => {
    // `{"text": ""}` es el keep-alive del backend: no debe repintar la burbuja.
    const onToken = vi.fn();
    stubFetch(sseChunks(['data: {"text": ""}\n', 'data: {"otro": 1}\n']));

    const result = await streamAsk({ question: "q", onToken });
    expect(onToken).not.toHaveBeenCalled();
    expect(result.answer).toBe("");
  });

  it("termina limpio si el stream se cierra sin [DONE]", async () => {
    stubFetch(sseChunks(['data: {"text": "cortado"}\n']));

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.answer).toBe("cortado");
  });

  it("un fragmento incompleto al cerrarse el stream se descarta", async () => {
    // Queda en el buffer y nunca se cierra: emitirlo mostraría medio JSON.
    stubFetch(sseChunks(['data: {"text": "ok"}\n', 'data: {"text": "a medi']));

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.answer).toBe("ok");
  });

  it("los callbacks opcionales pueden faltar sin romper el parseo", async () => {
    stubFetch(
      sseChunks([
        'data: {"fuentes_documentos": [{"id_externo": "X1", "chunks": []}]}\n',
        'data: {"degraded": true, "reason": "sin_llm"}\n',
        'data: {"resumen_meta": {"has_pliego_text": false, "truncated": false, "documentos": []}}\n',
      ]),
    );

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.fuentes).toHaveLength(1);
    expect(result.degraded?.reason).toBe("sin_llm");
    expect(result.resumenMeta?.has_pliego_text).toBe(false);
  });

  it("`degraded` sin reason ni docs cae a valores neutros", async () => {
    stubFetch(sseChunks(['data: {"degraded": true}\n']));

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.degraded).toEqual({ reason: "unknown", docs: [] });
  });

  it("`degraded` con docs que no son lista no propaga basura", async () => {
    stubFetch(sseChunks(['data: {"degraded": true, "reason": "x", "docs": "nope"}\n']));

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.degraded?.docs).toEqual([]);
  });
});

describe("respuesta no-SSE", () => {
  it("una respuesta JSON con `answer` se entrega entera de una vez", async () => {
    stubFetch(
      new Response(JSON.stringify({ answer: "respuesta completa" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const tokens: string[] = [];
    const result = await streamAsk({ question: "q", onToken: (acc) => tokens.push(acc) });
    expect(result.answer).toBe("respuesta completa");
    expect(tokens).toEqual(["respuesta completa"]);
  });

  it("acepta `text` como alias de `answer`", async () => {
    stubFetch(
      new Response(JSON.stringify({ text: "por text" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.answer).toBe("por text");
  });

  it("un JSON sin respuesta enseña un texto explícito, no una burbuja vacía", async () => {
    stubFetch(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await streamAsk({ question: "q", onToken: () => {} });
    expect(result.answer).toBe("Sin respuesta disponible.");
  });
});

describe("parámetros de la petición", () => {
  function bodyOf(fetchMock: ReturnType<typeof stubFetch>): Record<string, unknown> {
    return JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
  }

  it("top_k por defecto es 10 y se puede sobreescribir", async () => {
    const f1 = stubFetch(sseChunks(["data: [DONE]\n"]));
    await streamAsk({ question: "q", onToken: () => {} });
    expect(bodyOf(f1).top_k).toBe(10);

    vi.unstubAllGlobals();
    const f2 = stubFetch(sseChunks(["data: [DONE]\n"]));
    await streamAsk({ question: "q", topK: 3, onToken: () => {} });
    expect(bodyOf(f2).top_k).toBe(3);
  });

  it("los extras de los filtros globales viajan en el cuerpo", async () => {
    const f = stubFetch(sseChunks(["data: [DONE]\n"]));
    await streamAsk({
      question: "q",
      extras: { ccaa: "Madrid", tecnologia: "SAP" },
      onToken: () => {},
    });
    expect(bodyOf(f)).toMatchObject({ ccaa: "Madrid", tecnologia: "SAP" });
  });

  it("un modelo vacío no viaja como cadena vacía", async () => {
    const f = stubFetch(sseChunks(["data: [DONE]\n"]));
    await streamAsk({ question: "q", model: "", onToken: () => {} });
    expect(bodyOf(f).model).toBeUndefined();
  });

  it("la sesión va por cookie en las dos rutas", async () => {
    const f = stubFetch(sseChunks(["data: [DONE]\n"]));
    await streamAsk({ question: "q", onToken: () => {} });
    expect((f.mock.calls[0][1] as RequestInit).credentials).toBe("include");
  });

  it("propaga el AbortSignal para poder cancelar la respuesta", async () => {
    const f = stubFetch(sseChunks(["data: [DONE]\n"]));
    const controller = new AbortController();
    await streamAsk({ question: "q", signal: controller.signal, onToken: () => {} });
    expect((f.mock.calls[0][1] as RequestInit).signal).toBe(controller.signal);
  });

  it("streamResumen lanza si el endpoint responde error", async () => {
    stubFetch(new Response("", { status: 503 }));
    await expect(
      streamResumen({ idExterno: "X1", onToken: () => {} }),
    ).rejects.toThrow("Error 503");
  });
});
