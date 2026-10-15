"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { Send, Square, X } from "lucide-react";
import { ROTULO_DATO } from "@/components/console/panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useChat } from "@/hooks/use-ask";
import { useAsistente, type ContextoAsistente } from "@/lib/asistente-store";
import { cn } from "@/lib/utils";

// El hilo es lo único pesado del asistente: pinta Markdown con react-markdown y
// remark-gfm. Entra bajo demanda para que no lo lleve el First Load de ninguna
// pantalla. El panel —cabecera, sugerencias, caja de texto— se abre sin
// esperarlo, y la primera pregunta sale a la red mientras el hilo llega.
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
 * el panel o al enfocar una barra de pregunta. Un fallo se ignora: `ChatThread`
 * lo reintenta al montarse.
 */
export function precargarHilo(): void {
  import("@/components/chat-thread").catch(() => undefined);
}

const PREGUNTAS_GENERALES = [
  "¿Cuáles son las licitaciones más recientes?",
  "¿Qué es un PCAP y qué contiene?",
  "¿Cómo funciona el procedimiento abierto simplificado?",
  "Licitaciones de S/4HANA con importe mayor a 500K",
];

const PREGUNTAS_EXPEDIENTE = [
  "¿Qué solvencia técnica y económica exige?",
  "¿Cuáles son los criterios de adjudicación?",
  "¿Qué plazo de ejecución tiene?",
];

const PREGUNTAS_COMPARACION = [
  "¿Cuál exige más solvencia técnica?",
  "¿Qué plazo de ejecución tiene cada uno?",
  "¿En qué se diferencian sus criterios de adjudicación?",
];

/** Qué hace el asistente con el contexto que tiene: la frase de la cabecera. */
function descripcion({ expedientes }: ContextoAsistente): string {
  if (expedientes.length === 0) {
    return "Pregunta lo que quieras. Si hay licitaciones que vengan al caso, responde con ellas y las cita; si no, con conocimiento general.";
  }
  if (expedientes.length === 1) {
    return "Pregunta sobre esta licitación o pide su resumen. Si los pliegos están procesados, responde con su contenido y cita los fragmentos.";
  }
  return `Pregunta sobre los ${expedientes.length} expedientes a la vez: la respuesta cita cada dato con su expediente y la página del pliego de la que sale.`;
}

function marcador({ expedientes }: ContextoAsistente): string {
  if (expedientes.length === 0) return "Escribe una pregunta…";
  if (expedientes.length === 1) return "Pregunta sobre esta licitación y sus pliegos…";
  return `Pregunta sobre los ${expedientes.length} expedientes…`;
}

/** Un botón de sugerencia: de verdad (teclado y foco de serie), no una insignia. */
function Sugerencia({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      className={cn(
        buttonVariants({ variant: "outline", size: "sm" }),
        "h-auto min-h-8 py-1.5 text-left whitespace-normal md:h-auto",
      )}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/**
 * El asistente: una sola conversación sobre las licitaciones, en un panel
 * lateral, para toda la consola.
 *
 * Hasta 2026-10 eran tres —el copiloto global, el chat lateral del
 * Investigador y la pestaña IA de la ficha— con tres estados y tres cajas de
 * texto para la misma llamada (`POST /ask`). Este es el único: se monta una vez
 * en el layout del dashboard y cada entrada lo abre con su contexto
 * (`lib/asistente-store.ts`). Conserva todo lo que hacían los tres: respuesta
 * en streaming, citas del pliego, el resumen del expediente (un turno más del
 * hilo, con «Regenerar»), los pulgares de cada respuesta y el historial de la
 * conversación en curso, que sigue ahí al cerrarlo y volver a abrirlo.
 *
 * **El contexto es de cada pregunta**, como lo era en el Investigador: abrirlo
 * desde otra ficha cambia sobre qué responde la siguiente pregunta, no borra
 * las anteriores, y cada turno recuerda sobre qué se preguntó (el hilo avisa si
 * la respuesta no pudo usar el expediente pedido). «Nueva conversación» empieza
 * de cero.
 *
 * **No es modal**: la pantalla de detrás se sigue usando. En el Investigador se
 * marcan resultados con el panel abierto y el contexto cambia en el acto; en
 * Detalle se recorre la tabla sin cerrarlo. Escape lo cierra, y pulsar fuera
 * no: pulsar fuera es seguir trabajando.
 *
 * La IA se nombra, no se adorna: título en texto, sin destellos.
 */
export function AsistentePanel() {
  const abierto = useAsistente((s) => s.abierto);
  const setAbierto = useAsistente((s) => s.setAbierto);
  const contexto = useAsistente((s) => s.contexto);
  const opciones = useAsistente((s) => s.opciones);
  const pedido = useAsistente((s) => s.pedido);
  const atender = useAsistente((s) => s.atender);
  const quitarExpediente = useAsistente((s) => s.quitarExpediente);

  const { messages, streaming, loading, error, send, resumir, regenerarResumen, stop, reset } = useChat();
  const [input, setInput] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => precargarHilo(), []);

  const expedientes = contexto.expedientes;
  const unExpediente = expedientes.length === 1 ? expedientes[0] : null;

  const preguntar = React.useCallback(
    (pregunta: string, nueva = false) => {
      const q = pregunta.trim();
      if (!q) return;
      if (nueva) reset();
      // Los expedientes van en cada pregunta, también vacíos («sobre todas»):
      // así cada turno sabe sobre qué se pidió.
      void send(q, { ...opciones, idsExternos: expedientes.map((e) => e.id) });
    },
    [send, reset, opciones, expedientes],
  );

  const pedirResumen = React.useCallback(() => {
    if (!unExpediente) return;
    void resumir({ idExterno: unExpediente.id, titulo: unExpediente.titulo, model: opciones.model });
  }, [resumir, unExpediente, opciones.model]);

  const regenerar = React.useCallback(
    (indice: number) => void regenerarResumen(indice, { model: opciones.model }),
    [regenerarResumen, opciones.model],
  );

  // Lo que pidió la entrada que lo abrió: una pregunta (la barra del Resumen,
  // la caja del Investigador) o el resumen. Se atiende una vez, por su clave:
  // la referencia lo garantiza también cuando el efecto corre dos veces al
  // montar (el modo estricto de React en desarrollo), que si no mandaría la
  // pregunta dos veces.
  const atendido = React.useRef(0);
  React.useEffect(() => {
    if (!pedido || pedido.clave === atendido.current) return;
    atendido.current = pedido.clave;
    atender(pedido.clave);
    if (pedido.tipo === "pregunta") preguntar(pedido.texto, pedido.nueva);
    else pedirResumen();
  }, [pedido, atender, preguntar, pedirResumen]);

  const enviar = (evento?: React.FormEvent) => {
    evento?.preventDefault();
    if (!input.trim()) return;
    preguntar(input);
    setInput("");
  };

  const hayConversacion = messages.length > 0 || loading || Boolean(error);
  const sugerencias =
    expedientes.length === 0 ? PREGUNTAS_GENERALES : unExpediente ? PREGUNTAS_EXPEDIENTE : PREGUNTAS_COMPARACION;

  return (
    <Sheet open={abierto} onOpenChange={setAbierto} modal={false}>
      <SheetContent
        side="right"
        className="flex w-full flex-col sm:max-w-lg"
        // Pulsar fuera es seguir trabajando en la pantalla, no cerrar.
        onInteractOutside={(evento) => evento.preventDefault()}
        onOpenAutoFocus={(evento) => {
          evento.preventDefault();
          inputRef.current?.focus();
        }}
      >
        <SheetHeader className="text-left">
          <SheetTitle>Asistente</SheetTitle>
          <SheetDescription>{descripcion(contexto)}</SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex-1 overflow-y-auto pr-1">
          {hayConversacion ? (
            <ChatThread
              messages={messages}
              streaming={streaming}
              loading={loading}
              error={error}
              onRegenerarResumen={regenerar}
            />
          ) : (
            <div className="space-y-2">
              {unExpediente && (
                <Button size="sm" onClick={pedirResumen}>
                  Resumir el expediente
                </Button>
              )}
              <p className="text-tf-meta font-medium text-muted-foreground">Preguntas de ejemplo</p>
              <div className="flex flex-wrap gap-2">
                {sugerencias.map((q) => (
                  <Sugerencia key={q} onClick={() => preguntar(q)}>
                    {q}
                  </Sugerencia>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="mt-3 space-y-2 border-t border-border pt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={ROTULO_DATO}>Sobre</span>
            {expedientes.length === 0 ? (
              <span className="text-tf-meta text-muted-foreground">todas las licitaciones</span>
            ) : (
              expedientes.map((e) => (
                <Button
                  key={e.id}
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => quitarExpediente(e.id)}
                  aria-label={`Quitar ${e.titulo} del asistente`}
                  className="max-w-full"
                >
                  <span className="max-w-56 truncate">{e.titulo}</span>
                  <X aria-hidden="true" />
                </Button>
              ))
            )}
          </div>

          <form onSubmit={enviar} className="flex items-center gap-2">
            <Input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={marcador(contexto)}
              aria-label="Pregunta al asistente"
            />
            {streaming || loading ? (
              <Button type="button" onClick={stop} size="icon" variant="outline" aria-label="Detener">
                <Square aria-hidden="true" />
              </Button>
            ) : (
              <Button type="submit" disabled={!input.trim()} size="icon" aria-label="Enviar">
                <Send aria-hidden="true" />
              </Button>
            )}
          </form>

          {hayConversacion && !loading && (
            <div className="flex flex-wrap items-center gap-2">
              {unExpediente && (
                <Button variant="ghost" size="sm" onClick={pedirResumen}>
                  Resumir el expediente
                </Button>
              )}
              {messages.length > 0 && (
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
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
