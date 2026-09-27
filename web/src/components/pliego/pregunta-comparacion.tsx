"use client";

import * as React from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatThread } from "@/components/chat-thread";
import { useChat } from "@/hooks/use-ask";

/**
 * F2.8 — preguntar sobre los expedientes de la bandeja, a la vez.
 *
 * La tabla de al lado compara las fichas sin síntesis; esto es la otra mitad:
 * «¿cuál exige más solvencia técnica?» sobre los dos o tres pliegos. La
 * API reparte el contexto entre ellos y cita cada dato con su expediente;
 * si alguno no cargó o llegó recortado, el hilo lo dice (`ComparacionNotice`).
 *
 * Cambiar los expedientes de la bandeja empieza una conversación nueva: el
 * historial de una comparación no sirve para otra.
 */
export function PreguntaComparacion({
  ids,
  etiquetas,
}: {
  ids: string[];
  etiquetas: Record<string, string>;
}) {
  const chat = useChat({ idsExternos: ids });
  const [input, setInput] = React.useState("");
  const tituloId = React.useId();
  const clave = ids.join("|");
  const { reset } = chat;

  React.useEffect(() => {
    reset();
  }, [clave, reset]);

  const enviar = () => {
    const q = input.trim();
    if (!q) return;
    void chat.send(q);
    setInput("");
  };

  return (
    <section aria-labelledby={tituloId} className="mt-6 space-y-3 border-t border-border/70 pt-4">
      <div>
        <h3 id={tituloId} className="text-tf-body font-semibold">
          Preguntar sobre estos {ids.length} expedientes
        </h3>
        <p className="mt-1 text-tf-meta text-muted-foreground">
          {ids.map((id) => etiquetas[id] ?? id).join(" · ")}. La respuesta cita cada dato con su
          expediente y la página del pliego de la que sale.
        </p>
      </div>

      <ChatThread
        messages={chat.messages}
        streaming={chat.streaming}
        loading={chat.loading}
        error={chat.error}
        expectLicitacionContext
      />

      <div className="flex items-center gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") enviar();
          }}
          placeholder="¿Cuál exige más solvencia técnica? ¿Qué plazo de ejecución tiene cada uno?"
          aria-label="Pregunta sobre los expedientes comparados"
        />
        {chat.streaming || chat.loading ? (
          <Button onClick={chat.stop} size="icon" variant="outline" aria-label="Detener">
            <Square aria-hidden="true" />
          </Button>
        ) : (
          <Button onClick={enviar} disabled={!input.trim()} size="icon" aria-label="Enviar pregunta">
            <Send aria-hidden="true" />
          </Button>
        )}
      </div>
    </section>
  );
}
