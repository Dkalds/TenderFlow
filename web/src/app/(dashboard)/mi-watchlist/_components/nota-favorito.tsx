"use client";

/**
 * Nota personal de un favorito, leída y editada en la propia fila (CU-03).
 *
 * `PUT /watchlist/items/{id}/nota` existía y el listado ya traía la nota, pero
 * ninguna pantalla la enseñaba ni dejaba escribirla: el caso de uso se
 * recorría por la API y no por la consola.
 *
 * La nota es de quien la escribe, no de la organización: en un favorito
 * compartido cada persona tiene la suya (ver `WatchlistRepository.set_nota`).
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MAX_NOTA_FAVORITO, useSetWatchlistNota } from "@/hooks/use-watchlist-items";
import { cn } from "@/lib/utils";

interface PropsNota {
  idExterno: string;
  nota: string | null | undefined;
  /** Para nombrar el campo ante un lector de pantalla: hay una fila por favorito. */
  titulo: string;
  editando: boolean;
  onTerminar: () => void;
}

export function NotaFavorito({ editando, nota, ...resto }: PropsNota) {
  if (editando) {
    // El editor se monta al abrirlo, así que parte siempre de la nota vigente
    // y no de un borrador que alguien canceló.
    return <EditorNota nota={nota} {...resto} />;
  }
  if (!nota) return null;
  return <p className="text-tf-meta text-muted-foreground mt-1 line-clamp-3 whitespace-pre-line">{nota}</p>;
}

function EditorNota({ idExterno, nota, titulo, onTerminar }: Omit<PropsNota, "editando">) {
  const guardar = useSetWatchlistNota();
  const [borrador, setBorrador] = React.useState(nota ?? "");
  const id = React.useId();
  const campo = React.useRef<HTMLTextAreaElement>(null);

  // El editor se abre con un clic en «Añadir/Editar la nota»: el foco tiene
  // que seguir a esa intención y caer en el campo, no quedarse en el botón.
  React.useEffect(() => {
    campo.current?.focus();
  }, []);

  const sinCambios = borrador.trim() === (nota ?? "").trim();
  const enviar = () => {
    if (sinCambios) {
      onTerminar();
      return;
    }
    guardar.mutate({ idExterno, nota: borrador });
    onTerminar();
  };

  return (
    <form
      className="mt-2 space-y-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        enviar();
      }}
    >
      <label htmlFor={id} className="sr-only">
        Nota sobre {titulo}
      </label>
      <Textarea
        id={id}
        ref={campo}
        rows={3}
        maxLength={MAX_NOTA_FAVORITO}
        value={borrador}
        placeholder="Lo que quieras recordar de este expediente. Solo la ves tú."
        aria-describedby={`${id}-contador`}
        onChange={(event) => setBorrador(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onTerminar();
          } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            enviar();
          }
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={guardar.isPending}>
          {borrador.trim() || !nota ? "Guardar nota" : "Borrar nota"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onTerminar}>
          Cancelar
        </Button>
        <span
          id={`${id}-contador`}
          className={cn(
            "tf-tnum text-tf-micro ml-auto",
            borrador.length >= MAX_NOTA_FAVORITO ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {borrador.length} / {MAX_NOTA_FAVORITO}
        </span>
      </div>
    </form>
  );
}
