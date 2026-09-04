"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, apiGet } from "@/lib/api-client";
import {
  streamAsk,
  type AskMeta,
  type ChatMessage,
  type DegradedInfo,
  type FuenteDocumento,
} from "@/lib/ask-stream";
import { askKeys } from "@/lib/query-keys";

/**
 * Available LLM models for the copilot (shared cache key with /investigador).
 *
 * La forma de la respuesta (`AskModelInfo`) sale del esquema: antes se leía
 * `data.models` sobre un `any`, con una rama que además aceptaba un array
 * pelado que la API nunca ha devuelto.
 *
 * Un error HTTP degrada a lista vacía —el selector de modelo se queda con el
 * valor por defecto en vez de tumbar el panel—, igual que hacía el `if (!res.
 * ok) return []` anterior. Los fallos de red siguen propagándose.
 */
export function useAskModels() {
  return useQuery<string[]>({
    queryKey: askKeys.models,
    queryFn: async () => {
      try {
        return (await apiGet("/api/v1/ask/models")).models;
      } catch (error) {
        if (error instanceof ApiError) return [];
        throw error;
      }
    },
    staleTime: Infinity,
    meta: { silent: true },
  });
}

/** Client-side truncation of the history sent to the backend (server re-trims). */
const MAX_HISTORY_TURNS = 12;

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  /** Pliego/corpus citations attached to an assistant turn. */
  fuentes?: FuenteDocumento[];
  /** Set when the backend degraded (no LLM synthesis) for this turn. */
  degraded?: DegradedInfo | null;
  /** Effective scope of the answer (licitación vs corpus fallback). */
  askMeta?: AskMeta | null;
}

export interface SendOptions {
  model?: string;
  topK?: number;
  /** Extra body params (e.g. ccaa, tecnologia from global filters). */
  extras?: Record<string, unknown>;
}

export interface UseChatResult {
  messages: ChatTurn[];
  streaming: boolean;
  loading: boolean;
  error: string | null;
  send: (question: string, opts?: SendOptions) => Promise<void>;
  stop: () => void;
  reset: () => void;
}

/**
 * Multi-turn chat over `streamAsk`. The history lives only in this hook's
 * state (never persisted); each `send` posts the previous turns as `messages`
 * so the model keeps the conversation context.
 */
export function useChat(opts?: { idExterno?: string }): UseChatResult {
  const idExterno = opts?.idExterno;
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatTurn[]>([]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const updateLastAssistant = useCallback((patch: Partial<ChatTurn>) => {
    setMessages((prev) => {
      if (prev.length === 0 || prev[prev.length - 1].role !== "assistant") return prev;
      const next = prev.slice();
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }, []);

  const send = useCallback(
    async (question: string, sendOpts?: SendOptions) => {
      const q = question.trim();
      if (!q) return;

      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      const history: ChatMessage[] = messagesRef.current
        .filter((m) => m.content.trim())
        .slice(-MAX_HISTORY_TURNS)
        .map(({ role, content }) => ({ role, content }));

      setMessages((prev) => [...prev, { role: "user", content: q }, { role: "assistant", content: "" }]);
      setLoading(true);
      setError(null);
      setStreaming(true);

      try {
        const result = await streamAsk({
          question: q,
          messages: history,
          idExterno,
          model: sendOpts?.model,
          topK: sendOpts?.topK,
          extras: sendOpts?.extras,
          signal: abort.signal,
          onToken: (accumulated) => updateLastAssistant({ content: accumulated }),
          onFuentes: (fuentes) => updateLastAssistant({ fuentes }),
          onDegraded: (degraded) => updateLastAssistant({ degraded }),
          onAskMeta: (askMeta) => updateLastAssistant({ askMeta }),
        });
        updateLastAssistant({
          content: result.answer,
          fuentes: result.fuentes.length > 0 ? result.fuentes : undefined,
          degraded: result.degraded,
          askMeta: result.askMeta,
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (abortRef.current !== abort) return; // superseded by a newer send
        setError(err instanceof Error ? err.message : "Error desconocido");
        // Drop the empty assistant placeholder so the thread stays consistent.
        setMessages((prev) =>
          prev.length > 0 && prev[prev.length - 1].role === "assistant" && !prev[prev.length - 1].content
            ? prev.slice(0, -1)
            : prev,
        );
      } finally {
        // A newer send may already own the loading/streaming flags.
        if (abortRef.current === abort) {
          setLoading(false);
          setStreaming(false);
        }
      }
    },
    [idExterno, updateLastAssistant],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setLoading(false);
    setStreaming(false);
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setError(null);
    setStreaming(false);
    setLoading(false);
  }, []);

  return { messages, streaming, loading, error, send, stop, reset };
}
