/**
 * Shared client for the AI endpoints (POST /api/v1/ask and
 * POST /api/v1/licitaciones/{id}/resumen).
 *
 * Handles SSE streaming (with a plain-JSON fallback) and parses every event of
 * the contract: `{text}` tokens, `fuentes_documentos` (pliego citations),
 * `degraded` (fallback without LLM synthesis) and `resumen_meta`.
 */

import { getCsrfToken } from "./api-client";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface FuenteChunk {
  chunk_index?: number;
  texto?: string;
  tipo?: string;
  filename?: string;
}

export interface FuenteDocumento {
  id_externo: string | null;
  titulo?: string | null;
  chunks: FuenteChunk[];
}

export interface DegradedInfo {
  reason: string;
  docs: Record<string, unknown>[];
}

export interface ResumenMeta {
  has_pliego_text: boolean;
  truncated: boolean;
  documentos: { tipo: string | null; filename: string | null; status: string | null }[];
}

export interface AskStreamResult {
  answer: string;
  fuentes: FuenteDocumento[];
  degraded: DegradedInfo | null;
  resumenMeta: ResumenMeta | null;
}

interface StreamCallbacks {
  /** Called with the full accumulated answer each time new text arrives. */
  onToken: (accumulated: string) => void;
  onFuentes?: (fuentes: FuenteDocumento[]) => void;
  onDegraded?: (info: DegradedInfo) => void;
  onResumenMeta?: (meta: ResumenMeta) => void;
}

export interface AskParams extends StreamCallbacks {
  question: string;
  /** Previous conversation turns (multi-turn chat). Not persisted server-side. */
  messages?: ChatMessage[];
  /** Scope the context to one licitación (metadatos + fragmentos de pliegos). */
  idExterno?: string;
  model?: string;
  topK?: number;
  /** Extra body params (e.g. ccaa, tecnologia from global filters). */
  extras?: Record<string, unknown>;
  signal?: AbortSignal;
}

export interface ResumenParams extends StreamCallbacks {
  idExterno: string;
  model?: string;
  signal?: AbortSignal;
}

/** Parse the SSE body (or plain-JSON fallback) dispatching every known event. */
async function consumeStream(res: Response, cb: StreamCallbacks): Promise<AskStreamResult> {
  const result: AskStreamResult = { answer: "", fuentes: [], degraded: null, resumenMeta: null };

  const handleParsed = (parsed: Record<string, unknown>): void => {
    if (typeof parsed.text === "string" && parsed.text) {
      result.answer += parsed.text;
      cb.onToken(result.answer);
    } else if (Array.isArray(parsed.fuentes_documentos)) {
      result.fuentes = parsed.fuentes_documentos as FuenteDocumento[];
      cb.onFuentes?.(result.fuentes);
    } else if (parsed.degraded) {
      result.degraded = {
        reason: String(parsed.reason ?? "unknown"),
        docs: Array.isArray(parsed.docs) ? (parsed.docs as Record<string, unknown>[]) : [],
      };
      cb.onDegraded?.(result.degraded);
    } else if (parsed.resumen_meta && typeof parsed.resumen_meta === "object") {
      result.resumenMeta = parsed.resumen_meta as ResumenMeta;
      cb.onResumenMeta?.(result.resumenMeta);
    }
  };

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream") && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // Keep the incomplete last line in the buffer for the next chunk.
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data: ")) continue;
        const payload = trimmed.slice(6);
        if (payload === "[DONE]") return result;
        try {
          handleParsed(JSON.parse(payload));
        } catch {
          // Non-JSON SSE line — accumulate as raw text.
          result.answer += payload;
          cb.onToken(result.answer);
        }
      }
    }
    return result;
  }

  // Fallback: plain JSON response.
  const data = await res.json();
  result.answer = data.answer ?? data.text ?? "Sin respuesta disponible.";
  cb.onToken(result.answer);
  return result;
}

/**
 * POST a question and stream the answer. Resolves with the final result
 * (answer + fuentes/degraded metadata). Throws on non-OK responses; aborts are
 * surfaced as the standard AbortError.
 */
export async function streamAsk({
  question,
  messages,
  idExterno,
  model,
  topK = 10,
  extras,
  signal,
  ...callbacks
}: AskParams): Promise<AskStreamResult> {
  const csrf = getCsrfToken();
  const res = await fetch("/api/v1/ask", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify({
      question,
      messages: messages && messages.length > 0 ? messages : undefined,
      id_externo: idExterno || undefined,
      model: model || undefined,
      top_k: topK,
      ...extras,
    }),
    signal,
  });
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return consumeStream(res, callbacks);
}

/**
 * Generate the on-the-fly AI summary of one licitación (streaming, no cache).
 * The first SSE event is `resumen_meta` (pliego availability + document list).
 */
export async function streamResumen({
  idExterno,
  model,
  signal,
  ...callbacks
}: ResumenParams): Promise<AskStreamResult> {
  const csrf = getCsrfToken();
  const res = await fetch(`/api/v1/licitaciones/${encodeURIComponent(idExterno)}/resumen`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify({ model: model || undefined }),
    signal,
  });
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return consumeStream(res, callbacks);
}
