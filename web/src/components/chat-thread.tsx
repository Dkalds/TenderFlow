"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, FileText, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { MarkdownAnswer } from "@/components/markdown-answer";
import type { ChatTurn } from "@/hooks/use-ask";
import type { DegradedInfo, FuenteDocumento } from "@/lib/ask-stream";

/** Collapsible block with the pliego/corpus citations of one assistant turn. */
function FuentesBlock({ fuentes }: { fuentes: FuenteDocumento[] }) {
  const [open, setOpen] = React.useState(false);
  const totalChunks = fuentes.reduce((n, f) => n + (f.chunks?.length ?? 0), 0);
  if (totalChunks === 0) return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs font-medium"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <FileText className="h-3 w-3" />
        Fuentes del pliego ({totalChunks})
      </button>
      {/* Grid-rows trick: animates height without measuring it, and stays
          interruptible if the user toggles again mid-transition. */}
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out",
          open ? "mt-2 grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}
      >
        <div className="overflow-hidden">
          <div className="space-y-2">
            {fuentes.map((f, i) => (
              <div key={`${f.id_externo}-${i}`} className="border-border bg-muted/40 rounded-md border p-2">
                <div className="mb-1 text-xs font-medium">
                  {f.id_externo ? (
                    <a href={`/detalle?lic=${f.id_externo}`} className="text-primary hover:underline">
                      {f.id_externo}
                    </a>
                  ) : null}
                  {f.titulo ? <span className="text-muted-foreground"> — {f.titulo}</span> : null}
                </div>
                {f.chunks?.map((c, j) => (
                  <blockquote key={j} className="border-primary/40 text-muted-foreground mt-1 border-l-2 pl-2 text-xs">
                    {(c.tipo || c.filename) && (
                      <span className="font-medium">[{[c.tipo, c.filename].filter(Boolean).join(" · ")}] </span>
                    )}
                    {c.texto}
                  </blockquote>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Amber notice shown when the backend degraded (no LLM synthesis). */
function DegradedNotice({ degraded }: { degraded: DegradedInfo }) {
  const docs = degraded.docs ?? [];
  return (
    <div className="mt-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-2.5 text-xs" role="status">
      <p className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
        <TriangleAlert className="h-3.5 w-3.5" />
        El asistente no está disponible ahora mismo
        {degraded.reason === "timeout" ? " (tiempo de espera agotado)" : ""}.
      </p>
      {docs.length > 0 && (
        <div className="text-muted-foreground mt-1.5 space-y-1">
          <p>Licitaciones encontradas para tu consulta:</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {docs.map((d, i) => (
              <li key={i}>
                <a href={`/detalle?lic=${String(d.id_externo ?? "")}`} className="text-primary hover:underline">
                  {String(d.titulo ?? d.id_externo ?? "Licitación")}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export interface ChatThreadProps {
  messages: ChatTurn[];
  streaming: boolean;
  loading: boolean;
  error: string | null;
  className?: string;
}

/**
 * Presentational multi-turn chat thread (shared by the copilot panel, the
 * investigador page and the licitación AI tab). Inputs live in the parents.
 */
export function ChatThread({ messages, streaming, loading, error, className }: ChatThreadProps) {
  const bottomRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const last = messages[messages.length - 1];
  const waitingFirstToken = loading && last?.role === "assistant" && !last.content;

  return (
    <div className={cn("space-y-3", className)}>
      {messages.map((m, i) => {
        const isLast = i === messages.length - 1;
        if (m.role === "user") {
          return (
            <div key={i} className="flex justify-end">
              <div className="bg-muted max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">{m.content}</div>
            </div>
          );
        }
        return (
          <div key={i} className="text-sm">
            {m.content ? (
              <MarkdownAnswer text={m.content} />
            ) : isLast && waitingFirstToken ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
              </div>
            ) : null}
            {isLast && streaming && m.content ? (
              <span className="text-primary motion-safe:animate-pulse" aria-hidden="true">
                ▌
              </span>
            ) : null}
            {m.degraded ? <DegradedNotice degraded={m.degraded} /> : null}
            {m.fuentes && m.fuentes.length > 0 ? <FuentesBlock fuentes={m.fuentes} /> : null}
          </div>
        );
      })}

      {error && (
        <div
          className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border p-3 text-sm"
          role="alert"
        >
          {error}
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
