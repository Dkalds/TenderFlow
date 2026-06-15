"use client";

import { useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { streamAsk } from "@/lib/ask-stream";

/** Available LLM models for the copilot (shared cache key with /investigador). */
export function useAskModels() {
  return useQuery<string[]>({
    queryKey: ["ask-models"],
    queryFn: async () => {
      const res = await fetch("/api/v1/ask/models", { credentials: "include" });
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : (data.models ?? []);
    },
    staleTime: Infinity,
    meta: { silent: true },
  });
}

export interface UseAskResult {
  answer: string | null;
  streaming: boolean;
  loading: boolean;
  error: string | null;
  ask: (question: string, opts?: { model?: string; topK?: number }) => Promise<void>;
  reset: () => void;
}

/**
 * Stateful wrapper around `streamAsk` for the global copilot.
 * Manages answer/streaming/loading/error and aborts in-flight requests.
 */
export function useAsk(): UseAskResult {
  const [answer, setAnswer] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback(
    async (question: string, opts?: { model?: string; topK?: number }) => {
      const q = question.trim();
      if (!q) return;

      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setLoading(true);
      setError(null);
      setAnswer("");
      setStreaming(true);

      try {
        await streamAsk({
          question: q,
          model: opts?.model,
          topK: opts?.topK,
          signal: abort.signal,
          onToken: setAnswer,
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Error desconocido");
        setAnswer(null);
      } finally {
        setLoading(false);
        setStreaming(false);
      }
    },
    [],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setAnswer(null);
    setError(null);
    setStreaming(false);
    setLoading(false);
  }, []);

  return { answer, streaming, loading, error, ask, reset };
}
