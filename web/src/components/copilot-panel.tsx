"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { Send, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { ICONO_CONCEPTO } from "@/lib/iconos";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { useChat } from "@/hooks/use-ask";
import { useUiStore } from "@/lib/ui-store";

// El hilo es lo único pesado del copiloto: pinta Markdown con react-markdown y
// remark-gfm. Entra bajo demanda para que no lo lleven en el First Load ni el
// layout del dashboard ni /resumen, que importa de aquí `CopilotBar`. El panel
// —cabecera, ejemplos, caja de texto— se abre sin esperarlo, y la primera
// pregunta sale a la red mientras el hilo termina de llegar.
const ChatThread = dynamic(() => import("@/components/chat-thread").then((modulo) => modulo.ChatThread), {
  ssr: false,
  // Solo se monta cuando ya hay conversación, así que lo que se espera es una
  // respuesta: el mismo esqueleto que pinta el hilo antes del primer token.
  loading: () => (
    <div className="space-y-2" aria-busy="true">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
    </div>
  ),
});

/**
 * Adelanta la descarga del hilo en cuanto hay intención de preguntar: al abrir
 * el panel o al enfocar la barra. Para cuando llega la primera pregunta, ya
 * está. Un fallo se ignora: `ChatThread` lo reintenta al montarse.
 */
function precargarHilo(): void {
  import("@/components/chat-thread").catch(() => undefined);
}

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

/**
 * Copiloto: conversación de varios turnos sobre las licitaciones, en un panel
 * lateral. La IA se nombra, no se adorna: título en texto, sin destellos.
 */
export function CopilotPanel({ open, onOpenChange, seedQuestion, seedKey = 0, idExterno }: CopilotPanelProps) {
  const { messages, streaming, loading, error, send, stop, reset } = useChat({ idExterno });
  const [input, setInput] = React.useState("");

  React.useEffect(() => precargarHilo(), []);

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
          <SheetTitle>Copiloto</SheetTitle>
          <SheetDescription>
            Pregunta lo que quieras. Si hay licitaciones que vengan al caso, responde con ellas y las cita; si no, con
            conocimiento general.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex-1 overflow-y-auto pr-1">
          {!hasConversation && (
            <div className="space-y-2">
              <p className="text-tf-meta text-muted-foreground font-medium">Preguntas de ejemplo</p>
              {/* Botones de verdad y no insignias con `role="button"`: el
                  teclado (Intro y Espacio) y el foco vienen de serie. */}
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className={cn(
                      buttonVariants({ variant: "outline", size: "sm" }),
                      "h-auto min-h-8 py-1.5 text-left whitespace-normal md:h-auto",
                    )}
                    onClick={() => send(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {hasConversation && <ChatThread messages={messages} streaming={streaming} loading={loading} error={error} />}
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
                <Square aria-hidden="true" />
              </Button>
            ) : (
              <Button onClick={submit} disabled={!input.trim()} size="icon" aria-label="Enviar">
                <Send aria-hidden="true" />
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
 * El único `CopilotPanel`, montado una vez en el layout del dashboard. Lo
 * gobierna el store de UI, así que la barra del Resumen, la paleta y los atajos
 * abren el mismo panel.
 */
export function GlobalCopilot() {
  const open = useUiStore((s) => s.copilotOpen);
  const setOpen = useUiStore((s) => s.setCopilotOpen);
  const seed = useUiStore((s) => s.copilotSeed);
  return <CopilotPanel open={open} onOpenChange={setOpen} seedQuestion={seed.q} seedKey={seed.key} />;
}

/**
 * Campo de pregunta del Resumen: abre el copiloto global con lo escrito.
 *
 * Es un campo más de la consola. Tuvo un halo en degradado difuminado detrás,
 * sombra propia, fondo translúcido y un destello naranja: la firma de los
 * SaaS generados, y el único objeto con elevación de una pantalla plana. Ahora
 * es un campo con borde sobre la superficie opaca, el glifo de la IA en gris y
 * el botón «Preguntar» como único acento, porque es la acción.
 */
export function CopilotBar({ className }: { className?: string }) {
  const [input, setInput] = React.useState("");
  const openCopilot = useUiStore((s) => s.openCopilot);
  const IconoIa = ICONO_CONCEPTO.ia;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    openCopilot(q);
  };

  return (
    <form
      onSubmit={submit}
      // El foco se ve en el contenedor (el input no dibuja el suyo): el mismo
      // anillo que `Input`.
      className={cn(
        "border-border/60 bg-card focus-within:border-ring focus-within:ring-ring flex h-10 items-center gap-2 rounded-md border pr-1 pl-3 transition-colors focus-within:ring-1",
        className,
      )}
    >
      <IconoIa className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden="true" />
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        // Quien enfoca la barra va a preguntar: el hilo se pide ya.
        onFocus={precargarHilo}
        onPointerEnter={precargarHilo}
        placeholder="Pregúntale a tus licitaciones…"
        aria-label="Pregunta al copiloto"
        className="text-campo placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent outline-none focus-visible:outline-none"
      />
      <Button type="submit" size="sm" className="shrink-0">
        Preguntar
      </Button>
    </form>
  );
}
