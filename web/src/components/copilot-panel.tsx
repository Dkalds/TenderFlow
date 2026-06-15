"use client";

import * as React from "react";
import { Sparkles, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { useAsk } from "@/hooks/use-ask";
import { useUiStore } from "@/lib/ui-store";

const EXAMPLE_QUESTIONS = [
  "¿Cuáles son las licitaciones más recientes?",
  "¿Qué órganos licitan más en consultoría?",
  "Resumen de licitaciones de mantenimiento en Madrid",
  "Licitaciones de S/4HANA con importe mayor a 500K",
];

/** Render an answer, turning id_externo-like tokens into links to /detalle. */
function renderAnswer(text: string): React.ReactNode {
  const parts = text.split(/(\b[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+(?:-[A-Z0-9]+)*\b)/g);
  return parts.map((part, i) =>
    /^[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+/.test(part) ? (
      <a
        key={i}
        href={`/detalle?lic=${part}`}
        className="text-primary underline hover:no-underline"
      >
        {part}
      </a>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    ),
  );
}

interface CopilotPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Question to run when the panel opens; re-runs whenever `seedKey` changes. */
  seedQuestion?: string;
  seedKey?: number;
}

/** Slide-over copilot: asks the RAG endpoint and streams the answer. */
export function CopilotPanel({
  open,
  onOpenChange,
  seedQuestion,
  seedKey = 0,
}: CopilotPanelProps) {
  const { answer, streaming, loading, error, ask, reset } = useAsk();
  const [input, setInput] = React.useState("");

  // Run the seeded question each time the launcher submits a new one.
  React.useEffect(() => {
    if (seedKey > 0 && seedQuestion) {
      setInput(seedQuestion); // eslint-disable-line react-hooks/set-state-in-effect
      ask(seedQuestion);
    }
  }, [seedKey, seedQuestion, ask]);

  const submit = () => {
    if (input.trim()) ask(input);
  };

  const hasResult = answer != null || streaming || loading || error;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader className="text-left">
          <SheetTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Copiloto
          </SheetTitle>
          <SheetDescription>
            Pregúntale al corpus de licitaciones en lenguaje natural.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex items-center gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Escribe una pregunta…"
            aria-label="Pregunta al copiloto"
          />
          <Button onClick={submit} disabled={loading || !input.trim()} size="icon" aria-label="Enviar">
            <Send className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-4 flex-1 overflow-y-auto pr-1">
          {!hasResult && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Preguntas de ejemplo</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <Badge
                    key={q}
                    variant="outline"
                    role="button"
                    tabIndex={0}
                    className="cursor-pointer px-3 py-1.5 text-xs hover:bg-accent"
                    onClick={() => {
                      setInput(q);
                      ask(q);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setInput(q);
                        ask(q);
                      }
                    }}
                  >
                    {q}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {loading && !streaming && (
            <div className="space-y-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          )}

          {error && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive" role="alert">
              {error}
            </div>
          )}

          {(answer != null || streaming) && (
            <div className="whitespace-pre-wrap text-sm leading-relaxed">
              {answer ? renderAnswer(answer) : ""}
              {streaming && <span className="animate-pulse text-primary">▌</span>}
            </div>
          )}
        </div>

        {hasResult && !loading && (
          <Button
            variant="ghost"
            size="sm"
            className="mt-3 self-start"
            onClick={() => {
              reset();
              setInput("");
            }}
          >
            Nueva pregunta
          </Button>
        )}
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
  return (
    <CopilotPanel
      open={open}
      onOpenChange={setOpen}
      seedQuestion={seed.q}
      seedKey={seed.key}
    />
  );
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
          className="pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-r from-primary/40 via-primary/15 to-transparent opacity-70 blur-[6px]"
        />
        <div className="tf-card-shadow relative flex items-center gap-2 rounded-xl border border-border bg-card/80 p-2 pl-3">
          <Sparkles className="h-5 w-5 shrink-0 text-primary" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Pregúntale a tus licitaciones…"
            aria-label="Pregunta al copiloto"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <Button type="submit" size="sm" className="shrink-0">
            Preguntar
          </Button>
        </div>
      </form>
    </>
  );
}
