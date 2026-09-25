/**
 * Shared client for the AI endpoints (POST /api/v1/ask and
 * POST /api/v1/licitaciones/{id}/resumen).
 *
 * Handles SSE streaming (with a plain-JSON fallback) and parses every event of
 * the contract: `{text}` tokens, `fuentes_documentos` (pliego citations),
 * `degraded` (fallback without LLM synthesis) and `resumen_meta`.
 */

import { getCsrfToken } from "./api-client";
import { registrarEvento } from "./analytics";

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

/** Una cita del asistente ya validada por el backend contra el contexto enviado. */
export interface Fuente {
  documento_id: number;
  page_number: number | null;
  cita: string;
  tipo?: string | null;
  filename?: string | null;
  /** F2.8: expediente del documento citado, solo en preguntas cruzadas. */
  id_externo?: string | null;
}

/**
 * Evento `sources` (C5.3): las citas de la respuesta, validadas en servidor.
 *
 * `sinFuentes` llega **siempre** en modo licitación, también cuando no hay
 * ninguna: sin ese campo, «el pliego no lo sostiene» y «el evento no llegó» se
 * pintarían igual, que es justo lo que la cita venía a evitar.
 */
export interface SourcesInfo {
  sources: Fuente[];
  sinFuentes: boolean;
  /** Marcadores que apuntaban a documentos ausentes del contexto. */
  descartadas: number;
}

export interface ResumenMeta {
  has_pliego_text: boolean;
  truncated: boolean;
  /** True cuando el resumen se sirvió del caché del servidor (sin llamada LLM). */
  cached?: boolean;
  documentos: { tipo: string | null; filename: string | null; status: string | null }[];
}

/**
 * Ámbito EFECTIVO de la respuesta. Si se pidió `id_externo` pero el backend no
 * pudo cargar el contexto de esa licitación, degrada al corpus general y aquí
 * llega `contexto: "general"` — la UI debe avisarlo en vez de presentar la
 * respuesta como si fuera del expediente.
 */
export interface AskMeta {
  contexto: "licitacion" | "general" | "comparacion";
  id_externo?: string | null;
  /** F2.8 — en una pregunta cruzada, los expedientes pedidos, en orden. */
  ids_externos?: string[];
  /** F2.8 — qué entró de cada uno: si existe, cuánto pliego y si se recortó. */
  expedientes?: AskMetaExpediente[];
  /** F2.8 — algún expediente llegó al modelo con su parte del contexto recortada. */
  truncado?: boolean;
}

export interface AskMetaExpediente {
  id_externo: string;
  encontrado: boolean;
  has_pliego_text?: boolean;
  fragmentos?: number;
  truncado?: boolean;
}

export interface AskStreamResult {
  answer: string;
  fuentes: FuenteDocumento[];
  degraded: DegradedInfo | null;
  resumenMeta: ResumenMeta | null;
  askMeta: AskMeta | null;
  sources: SourcesInfo | null;
}

interface StreamCallbacks {
  /**
   * Recibe siempre la respuesta **acumulada**. Se llama como mucho una vez por
   * frame —los tokens que llegan dentro del mismo frame se entregan juntos— y
   * lo pendiente se entrega antes de que la promesa resuelva y antes de
   * cualquier otro evento del stream, así que el orden no cambia.
   */
  onToken: (accumulated: string) => void;
  onFuentes?: (fuentes: FuenteDocumento[]) => void;
  onDegraded?: (info: DegradedInfo) => void;
  onResumenMeta?: (meta: ResumenMeta) => void;
  onAskMeta?: (meta: AskMeta) => void;
  onSources?: (info: SourcesInfo) => void;
}

export interface AskParams extends StreamCallbacks {
  question: string;
  /** Previous conversation turns (multi-turn chat). Not persisted server-side. */
  messages?: ChatMessage[];
  /** Scope the context to one licitación (metadatos + fragmentos de pliegos). */
  idExterno?: string;
  /** F2.8 — pregunta cruzada sobre hasta tres licitaciones (la bandeja de comparación). */
  idsExternos?: string[];
  model?: string;
  topK?: number;
  /** Extra body params (e.g. ccaa, tecnologia from global filters). */
  extras?: Record<string, unknown>;
  signal?: AbortSignal;
}

export interface ResumenParams extends StreamCallbacks {
  idExterno: string;
  model?: string;
  /** Regenerate ignoring the server-side cache (the "Regenerar" button). */
  force?: boolean;
  signal?: AbortSignal;
}

/**
 * Programa `fn` para el próximo frame y devuelve cómo cancelarlo.
 *
 * `requestAnimationFrame` y no un temporizador: el frame es la unidad en la
 * que el navegador pinta, así que agrupar por frame es agrupar justo lo que se
 * iba a ver junto. Y con la pestaña oculta no dispara: el texto se acumula sin
 * repintar nada y sale entero al cerrar el stream o al volver a la pestaña.
 * Fuera del navegador cae a un temporizador de un frame.
 */
function programarFrame(fn: () => void): () => void {
  if (typeof requestAnimationFrame === "function") {
    const id = requestAnimationFrame(fn);
    return () => cancelAnimationFrame(id);
  }
  const id = setTimeout(fn, 16);
  return () => clearTimeout(id);
}

/** Parse the SSE body (or plain-JSON fallback) dispatching every known event. */
async function consumeStream(res: Response, cb: StreamCallbacks, signal?: AbortSignal): Promise<AskStreamResult> {
  const result: AskStreamResult = {
    answer: "",
    fuentes: [],
    degraded: null,
    resumenMeta: null,
    askMeta: null,
    sources: null,
  };

  // Tokens agrupados por frame. Un modelo rápido emite varios tokens por frame
  // y cada `onToken` acaba en un `setState` que repinta el hilo: entregarlos
  // uno a uno era trabajo que nadie llegaba a ver. Como el callback recibe
  // siempre el acumulado, agrupar no pierde texto.
  let tokenPendiente = false;
  let cancelarFrame: (() => void) | null = null;

  const entregarToken = (): void => {
    cancelarFrame?.();
    cancelarFrame = null;
    if (!tokenPendiente) return;
    tokenPendiente = false;
    // Tras un abort no se entrega nada: quien llamó ya pasó a otra cosa (otra
    // pregunta, «Nueva conversación») y pintar el texto viejo pisaría el turno
    // nuevo. Antes no hacía falta decirlo porque cada token salía en el acto.
    if (signal?.aborted) return;
    cb.onToken(result.answer);
  };

  const anotarToken = (): void => {
    tokenPendiente = true;
    if (cancelarFrame) return;
    cancelarFrame = programarFrame(() => {
      cancelarFrame = null;
      entregarToken();
    });
  };

  const handleParsed = (parsed: Record<string, unknown>): void => {
    if (typeof parsed.text === "string" && parsed.text) {
      result.answer += parsed.text;
      anotarToken();
      return;
    }
    // Los metadatos salen en el orden del stream: el texto que los precedía se
    // entrega antes que ellos.
    entregarToken();
    if (Array.isArray(parsed.fuentes_documentos)) {
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
    } else if (parsed.ask_meta && typeof parsed.ask_meta === "object") {
      result.askMeta = parsed.ask_meta as AskMeta;
      cb.onAskMeta?.(result.askMeta);
    } else if (Array.isArray(parsed.sources)) {
      // Llega al final del stream, cuando la respuesta ya está completa: las
      // citas solo se pueden validar sobre el texto entero.
      result.sources = {
        sources: parsed.sources as Fuente[],
        sinFuentes: parsed.sin_fuentes === true,
        descartadas: typeof parsed.descartadas === "number" ? parsed.descartadas : 0,
      };
      cb.onSources?.(result.sources);
    }
  };

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream") && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let terminado = false;

    try {
      while (!terminado) {
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
          if (payload === "[DONE]") {
            terminado = true;
            break;
          }
          try {
            handleParsed(JSON.parse(payload));
          } catch {
            // Non-JSON SSE line — accumulate as raw text.
            result.answer += payload;
            anotarToken();
          }
        }
      }
    } catch (err) {
      // Un corte de red a media respuesta entrega lo que sí llegó: la burbuja
      // enseña ese texto junto al error. (Un abort no entrega nada: lo filtra
      // `entregarToken`.)
      entregarToken();
      throw err;
    }
    entregarToken();
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
 *
 * Telemetría: se cuenta la pregunta que llega a tener respuesta (o rechazo del
 * servidor). Un abort del usuario o una caída de red no emiten nada — no son
 * "el asistente falló", y contarlos como tal ensuciaría la única métrica que
 * dice si esto sirve.
 */
export async function streamAsk({
  question,
  messages,
  idExterno,
  idsExternos,
  model,
  topK = 10,
  extras,
  signal,
  ...callbacks
}: AskParams): Promise<AskStreamResult> {
  const csrf = getCsrfToken();
  const varios = idsExternos && idsExternos.length > 0 ? idsExternos : undefined;
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
      ids_externos: varios,
      model: model || undefined,
      top_k: topK,
      ...extras,
    }),
    signal,
  });
  const ambito = idExterno || varios ? "licitacion" : "corpus";
  // F2.8: cuántos expedientes entraron (1-3, acotado por el endpoint). Solo
  // viaja en preguntas con expediente: en el corpus no hay nada que contar.
  const n = new Set([idExterno, ...(varios ?? [])].filter(Boolean)).size;
  const conteo = n >= 1 && n <= 3 ? { n_expedientes: String(n) as "1" | "2" | "3" } : {};
  if (!res.ok) {
    registrarEvento("asistente_usado", { modo: "pregunta", ambito, resultado: "error", ...conteo });
    throw new Error(`Error ${res.status}`);
  }
  const resultado = await consumeStream(res, callbacks, signal);
  // `degradado` es la respuesta sin síntesis del LLM: cuenta como uso, pero no
  // como uso que sirva. Separarlas es la única forma de ver si el asistente
  // aparenta funcionar. La pregunta, el modelo y la licitación no salen de aquí.
  registrarEvento("asistente_usado", {
    modo: "pregunta",
    ambito,
    resultado: resultado.degraded ? "degradado" : "ok",
    ...conteo,
  });
  return resultado;
}

/**
 * Generate (or serve cached) the AI summary of one licitación, streaming.
 * The first SSE event is `resumen_meta` (pliego availability + document list +
 * `cached`). Pass `force: true` to regenerate ignoring the server cache.
 */
export async function streamResumen({
  idExterno,
  model,
  force,
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
    body: JSON.stringify({ model: model || undefined, force: force || undefined }),
    signal,
  });
  if (!res.ok) {
    registrarEvento("asistente_usado", {
      modo: "resumen",
      ambito: "licitacion",
      resultado: "error",
    });
    throw new Error(`Error ${res.status}`);
  }
  const resultado = await consumeStream(res, callbacks, signal);
  registrarEvento("asistente_usado", {
    modo: "resumen",
    ambito: "licitacion",
    resultado: resultado.degraded ? "degradado" : "ok",
  });
  return resultado;
}
