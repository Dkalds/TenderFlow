/**
 * Tests for src/lib/ask-stream.ts — SSE parsing of the full event contract:
 * {text}, fuentes_documentos, degraded, resumen_meta and [DONE].
 */

import { describe, it, expect, vi, afterEach } from "vitest";
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
});
