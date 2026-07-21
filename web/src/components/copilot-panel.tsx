"use client";

import * as React from "react";
import { Sparkles, Send, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { ChatThread } from "@/components/chat-thread";
import { useChat } from "@/hooks/use-ask";
import { useUiStore } from "@/lib/ui-store";

const EXAMPLE_QUESTIONS = [
  "¿Cuáles son las licitaciones más recientes?",
  "¿Qué es un PCAP y qué contiene?",
  "¿Cómo funciona el procedimiento abierto simplificado?",
  "Licitaciones de S/4HANA con importe mayor a 500K",
];

interface CopilotPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Question to run when the panel opens; re-runs whenever `seedKey` changes. */
  seedQuestion?: string;
  seedKey?: number;
  /** Scope the conversation to one licitación (metadatos + pliegos). */
  idExterno?: string;
}

/** Slide-over copilot: multi-turn chat over the AI endpoint (streams answers). */
export function CopilotPanel({ open, onOpenChange, seedQuestion, seedKey = 0, idExterno }: CopilotPanelProps) {
  const { messages, streaming, loading, error, send, stop, reset } = useChat({ idExterno });
  const [input, setInput] = React.useState("");

  // Run the seeded question each time the launcher submits a new one.
  React.useEffect(() => {
    if (seedKey > 0 && seedQuestion) {
      setInput(""); // eslint-disable-line react-hooks/set-state-in-effect
      send(seedQuestion);
    }
  }, [seedKey, seedQuestion, send]);

  const submit = () => {
    const q = input.trim();
    if (!q) return;
    send(q);
    setInput("");
  };

  const hasConversation = messages.length > 0 || loading || error;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader className="text-left">
          <SheetTitle className="flex items-center gap-2">
            <Sparkles className="text-primary h-5 w-5" />
            Copiloto
          </SheetTitle>
          <SheetDescription>
            Pregunta lo que quieras: usa el corpus cuando hay expedientes relevantes (y los cita); si no, responde con
            conocimiento general.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex-1 overflow-y-auto pr-1">
          {!hasConversation && (
            <div className="space-y-2">
              <p className="text-muted-foreground text-xs font-medium">Preguntas de ejemplo</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <Badge
                    key={q}
                    variant="outline"
                    role="button"
                    tabIndex={0}
                    className="hover:bg-accent cursor-pointer px-3 py-1.5 text-xs"
                    onClick={() => send(q)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        send(q);
                      }
                    }}
                  >
                    {q}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <ChatThread messages={messages} streaming={streaming} loading={loading} error={error} />
        </div>

        <div className="border-border mt-3 space-y-2 border-t pt-3">
          <div className="flex items-center gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
              placeholder={idExterno ? "Pregunta sobre esta licitación…" : "Escribe una pregunta…"}
              aria-label="Pregunta al copiloto"
            />
            {streaming || loading ? (
              <Button onClick={stop} size="icon" variant="outline" aria-label="Detener">
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button onClick={submit} disabled={!input.trim()} size="icon" aria-label="Enviar">
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
          {messages.length > 0 && !loading && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                reset();
                setInput("");
              }}
            >
              Nueva conversación
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

/**
 * Single global CopilotPanel mounted once in the dashboard layout. Driven by the
 * UI store so the hero ask-bar, command palette and shortcuts share one panel.
 */
export function GlobalCopilot() {
  const open = useUiStore((s) => s.copilotOpen);
  const setOpen = useUiStore((s) => s.setCopilotOpen);
  const seed = useUiStore((s) => s.copilotSeed);
  return <CopilotPanel open={open} onOpenChange={setOpen} seedQuestion={seed.q} seedKey={seed.key} />;
}

/** Premium hero ask-bar that launches the global CopilotPanel via the UI store. */
export function CopilotBar({ className }: { className?: string }) {
  const [input, setInput] = React.useState("");
  const openCopilot = useUiStore((s) => s.openCopilot);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    openCopilot(q);
  };

  return (
    <>
      <form onSubmit={submit} className={cn("relative", className)}>
        <div
          aria-hidden="true"
          className="from-primary/40 via-primary/15 pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-r to-transparent opacity-70 blur-[6px]"
        />
        <div className="tf-card-shadow border-border bg-card/80 relative flex items-center gap-2 rounded-xl border p-2 pl-3">
          <Sparkles className="text-primary h-5 w-5 shrink-0" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Pregúntale a tus licitaciones…"
            aria-label="Pregunta al copiloto"
            className="placeholder:text-muted-foreground flex-1 bg-transparent text-sm outline-none"
          />
          <Button type="submit" size="sm" className="shrink-0">
            Preguntar
          </Button>
        </div>
      </form>
    </>
  );
}
