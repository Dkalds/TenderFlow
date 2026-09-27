"use client";

import * as React from "react";
import { Send, Square } from "lucide-react";
import { Aviso, PanelError } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AVISO_GENERADO, ChatThread, mensajeDeFalloIA } from "@/components/chat-thread";
import { FeedbackButtons } from "@/components/feedback-buttons";
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
 * Sección «Asistente IA» del detalle de una licitación: resumen ejecutivo en
 * streaming (cacheado en servidor por estado de documentos; «Regenerar» lo
 * fuerza) y chat contextualizado en el expediente y el contenido de sus
 * pliegos, con feedback de utilidad por respuesta.
 *
 * La IA se nombra, no se adorna: sin el destello delante del título ni dentro
 * del botón, y lo que genera va etiquetado como tal («Generado
 * automáticamente · revisa el pliego»), porque un resumen de modelo no es un
 * dato del expediente (ADR-014).
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

  const generarResumen = React.useCallback(
    async (force = false) => {
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
          force,
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
    },
    [idExterno],
  );

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
      <h3 className="text-tf-body font-semibold">Asistente IA</h3>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="resumen">Resumen</TabsTrigger>
          <TabsTrigger value="preguntar">Preguntar</TabsTrigger>
        </TabsList>

        <TabsContent value="resumen">
          {!hasResumen && (
            <div className="space-y-2">
              <p className="text-tf-body text-muted-foreground">
                Genera un resumen de la oportunidad y de sus pliegos con IA.
              </p>
              <Button size="sm" onClick={() => void generarResumen()}>
                Generar resumen
              </Button>
            </div>
          )}

          {meta && !meta.has_pliego_text && (
            <Aviso tone="warning" className="mb-3">
              Resumen basado solo en los datos del anuncio: los pliegos no están disponibles o aún no se
              han procesado.
              {meta.documentos.length > 0 && (
                <span className="mt-1 flex flex-wrap gap-1.5">
                  {meta.documentos.map((d, i) => (
                    <Badge key={i} variant="outline" size="sm">
                      {d.filename ?? d.tipo ?? "documento"} · {STATUS_LABELS[d.status ?? ""] ?? d.status}
                    </Badge>
                  ))}
                </span>
              )}
            </Aviso>
          )}

          {resumenLoading && !resumen && (
            <div className="space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          )}

          {/* Un solo aviso: el resumen no pasa por React Query, así que no
              hay toast que callar. Mensaje humano; el texto original, plegado. */}
          {resumenError && (
            <PanelError
              variant="inline"
              title="No se pudo generar el resumen"
              message={mensajeDeFalloIA(resumenError)}
              detail={resumenError}
              onRetry={() => void generarResumen()}
            />
          )}

          {resumenDegraded && !resumen && (
            <Aviso tone="warning">
              El asistente no está disponible ahora mismo. Inténtalo de nuevo en unos minutos.
            </Aviso>
          )}

          {resumen ? (
            <div>
              <MarkdownAnswer text={resumen} />
              {resumenLoading ? (
                <span className="text-primary motion-safe:animate-pulse" aria-hidden="true">
                  ▌
                </span>
              ) : (
                <p className="mt-2 text-tf-micro text-muted-foreground">{AVISO_GENERADO}</p>
              )}
            </div>
          ) : null}

          {resumen != null && resumen !== "" && !resumenLoading && !resumenDegraded && (
            <FeedbackButtons modo="resumen" />
          )}

          {resumen != null && !resumenLoading && (
            <div className="mt-2 flex items-center gap-2">
              {/* Regenerar fuerza al proveedor: el hit de caché ya se sirvió. */}
              <Button variant="ghost" size="sm" onClick={() => void generarResumen(true)}>
                Regenerar
              </Button>
              {meta?.cached && (
                <span className="text-tf-micro text-muted-foreground">
                  Resumen guardado de una generación anterior.
                </span>
              )}
            </div>
          )}
        </TabsContent>

        <TabsContent value="preguntar" className="space-y-3">
          {chat.messages.length === 0 && !chat.loading && (
            <p className="text-tf-body text-muted-foreground">
              Pregunta sobre esta licitación: plazos, solvencia, criterios de adjudicación… Si los pliegos están
              procesados, responde con su contenido y cita los fragmentos.
            </p>
          )}

          <ChatThread
            messages={chat.messages}
            streaming={chat.streaming}
            loading={chat.loading}
            error={chat.error}
            expectLicitacionContext
          />

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
                <Square aria-hidden="true" />
              </Button>
            ) : (
              <Button onClick={submitChat} disabled={!input.trim()} size="icon" aria-label="Enviar pregunta">
                <Send aria-hidden="true" />
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
