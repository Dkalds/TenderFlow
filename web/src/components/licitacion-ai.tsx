"use client";

import * as React from "react";
import { FileText, MessageSquare, RefreshCw, Send, Sparkles, Square } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChatThread } from "@/components/chat-thread";
import { MarkdownAnswer } from "@/components/markdown-answer";
import { useChat } from "@/hooks/use-ask";
import { streamResumen, type ResumenMeta } from "@/lib/ask-stream";

interface LicitacionAIProps {
  idExterno: string;
  /** Bump to activate the "Preguntar" tab from outside (header button). */
  askSignal?: number;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "pendiente",
  downloaded: "descargado",
  extracted: "procesado",
  error: "error",
};

/**
 * Sección "Asistente IA" del detalle de una licitación: resumen ejecutivo
 * generado al vuelo (streaming, sin caché) y chat contextualizado en el
 * expediente y el contenido de sus pliegos.
 */
export function LicitacionAI({ idExterno, askSignal = 0 }: LicitacionAIProps) {
  const [tab, setTab] = React.useState("resumen");

  // ── Resumen (on demand, streaming) ──────────────────────────────────────
  const [resumen, setResumen] = React.useState<string | null>(null);
  const [meta, setMeta] = React.useState<ResumenMeta | null>(null);
  const [resumenLoading, setResumenLoading] = React.useState(false);
  const [resumenError, setResumenError] = React.useState<string | null>(null);
  const [resumenDegraded, setResumenDegraded] = React.useState(false);
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const generarResumen = React.useCallback(async () => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setResumenLoading(true);
    setResumenError(null);
    setResumenDegraded(false);
    setResumen("");
    setMeta(null);

    try {
      const result = await streamResumen({
        idExterno,
        signal: abort.signal,
        onToken: setResumen,
        onResumenMeta: setMeta,
        onDegraded: () => setResumenDegraded(true),
      });
      if (!result.answer && result.degraded) setResumen(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setResumenError(err instanceof Error ? err.message : "Error desconocido");
      setResumen(null);
    } finally {
      if (abortRef.current === abort) setResumenLoading(false);
    }
  }, [idExterno]);

  // ── Chat contextualizado ────────────────────────────────────────────────
  const chat = useChat({ idExterno });
  const [input, setInput] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (askSignal > 0) {
      setTab("preguntar"); // eslint-disable-line react-hooks/set-state-in-effect
      // Focus after the tab content mounts.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [askSignal]);

  const submitChat = () => {
    const q = input.trim();
    if (!q) return;
    chat.send(q);
    setInput("");
  };

  const hasResumen = resumen != null || resumenLoading || resumenError || resumenDegraded;

  return (
    <div className="mb-6 space-y-3" id="licitacion-ai">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        <Sparkles className="text-primary h-4 w-4" />
        Asistente IA
      </h3>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="resumen">
            <FileText className="h-3.5 w-3.5" />
            Resumen
          </TabsTrigger>
          <TabsTrigger value="preguntar">
            <MessageSquare className="h-3.5 w-3.5" />
            Preguntar
          </TabsTrigger>
        </TabsList>

        <TabsContent value="resumen">
          {!hasResumen && (
            <div className="space-y-2">
              <p className="text-muted-foreground text-sm">
                Genera un resumen de la oportunidad y de sus pliegos con IA.
              </p>
              <Button size="sm" onClick={generarResumen} className="gap-1.5">
                <Sparkles className="h-3.5 w-3.5" />
                Generar resumen
              </Button>
            </div>
          )}

          {meta && !meta.has_pliego_text && (
            <div className="mb-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-2.5 text-xs text-amber-700 dark:text-amber-400">
              Resumen basado solo en los metadatos del anuncio: los pliegos no están disponibles o aún no se han
              procesado.
              {meta.documentos.length > 0 && (
                <span className="text-muted-foreground mt-1 flex flex-wrap gap-1.5">
                  {meta.documentos.map((d, i) => (
                    <Badge key={i} variant="outline" className="text-[10px]">
                      {d.filename ?? d.tipo ?? "documento"} · {STATUS_LABELS[d.status ?? ""] ?? d.status}
                    </Badge>
                  ))}
                </span>
              )}
            </div>
          )}

          {resumenLoading && !resumen && (
            <div className="space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          )}

          {resumenError && (
            <div
              className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border p-3 text-sm"
              role="alert"
            >
              {resumenError}
            </div>
          )}

          {resumenDegraded && !resumen && (
            <div className="rounded-md border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
              El asistente no está disponible ahora mismo. Inténtalo de nuevo en unos minutos.
            </div>
          )}

          {resumen ? (
            <div>
              <MarkdownAnswer text={resumen} />
              {resumenLoading && (
                <span className="text-primary motion-safe:animate-pulse" aria-hidden="true">
                  ▌
                </span>
              )}
            </div>
          ) : null}

          {resumen != null && !resumenLoading && (
            <Button variant="ghost" size="sm" className="mt-2 gap-1.5" onClick={generarResumen}>
              <RefreshCw className="h-3.5 w-3.5" />
              Regenerar
            </Button>
          )}
        </TabsContent>

        <TabsContent value="preguntar" className="space-y-3">
          {chat.messages.length === 0 && !chat.loading && (
            <p className="text-muted-foreground text-sm">
              Pregunta sobre esta licitación: plazos, solvencia, criterios de adjudicación… Si los pliegos están
              procesados, responde con su contenido y cita los fragmentos.
            </p>
          )}

          <ChatThread messages={chat.messages} streaming={chat.streaming} loading={chat.loading} error={chat.error} />

          <div className="flex items-center gap-2">
            <Input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitChat();
              }}
              placeholder="Pregunta sobre esta licitación y sus pliegos…"
              aria-label="Pregunta sobre la licitación"
            />
            {chat.streaming || chat.loading ? (
              <Button onClick={chat.stop} size="icon" variant="outline" aria-label="Detener">
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button onClick={submitChat} disabled={!input.trim()} size="icon" aria-label="Enviar pregunta">
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
          {chat.messages.length > 0 && !chat.loading && (
            <Button variant="ghost" size="sm" onClick={chat.reset}>
              Nueva conversación
            </Button>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
