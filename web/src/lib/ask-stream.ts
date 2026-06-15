/**
 * Shared client for the RAG copilot endpoint (POST /api/v1/ask).
 *
 * Handles SSE streaming (with a plain-JSON fallback) so both the global copilot
 * (useAsk / CopilotPanel) and the /investigador page use one implementation.
 */

export interface AskParams {
  question: string;
  model?: string;
  topK?: number;
  /** Extra body params (e.g. ccaa, tecnologia from global filters). */
  extras?: Record<string, unknown>;
  signal?: AbortSignal;
  /** Called with the full accumulated answer each time new text arrives. */
  onToken: (accumulated: string) => void;
}

/**
 * POST a question and stream the answer. Resolves with the final answer text.
 * Throws on non-OK responses; aborts are surfaced as the standard AbortError.
 */
export async function streamAsk({
  question,
  model,
  topK = 10,
  extras,
  signal,
  onToken,
}: AskParams): Promise<string> {
  const res = await fetch("/api/v1/ask", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      model: model || undefined,
      top_k: topK,
      ...extras,
    }),
    signal,
  });
  if (!res.ok) throw new Error(`Error ${res.status}`);

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream") && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let accumulated = "";
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
        if (payload === "[DONE]") return accumulated;
        try {
          const parsed = JSON.parse(payload);
          if (parsed.text) {
            accumulated += parsed.text;
            onToken(accumulated);
          }
        } catch {
          // Non-JSON SSE line — accumulate as raw text.
          accumulated += payload;
          onToken(accumulated);
        }
      }
    }
    return accumulated;
  }

  // Fallback: plain JSON response.
  const data = await res.json();
  const answer = data.answer ?? data.text ?? "Sin respuesta disponible.";
  onToken(answer);
  return answer;
}
