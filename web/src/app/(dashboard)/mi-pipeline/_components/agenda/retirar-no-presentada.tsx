"use client";

/**
 * Confirmar que una oportunidad que ya no admite oferta **no se presentó** —o
 * que no se presentaron varias, de una vez.
 *
 * Es el gesto de la agenda sin deshacer: `withdrawn` es un estado terminal y la
 * API no reabre, así que aquí sí hay diálogo — a diferencia de completar una
 * tarea o descartar una señal, que se deshacen desde el aviso.
 *
 * No pregunta el motivo, como hace el cierre del tablero: lo que el botón
 * afirma («No nos presentamos») **es** el motivo, `no_presentada` en la lista
 * cerrada de D37. Hacerlo elegir en un desplegable sería pedir dos veces lo
 * mismo. Quien se retiró por otra causa —precio, solvencia— la registra desde
 * la ficha, donde está la lista entera.
 *
 * **Varias a la vez**, porque se acumulan: cinco plazos pasados eran cinco
 * diálogos idénticos. Con más de una se listan con su casilla, todas marcadas:
 * la que sí se presentó se desmarca y se queda donde estaba, para registrarla
 * en su ficha. Una confirmación sobre una lista que se puede leer y recortar es
 * una confirmación de verdad; cinco «Retirar» seguidos acaban siendo un tic.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { formatDate, formatNumber } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { claveDe } from "./agenda-meta";
import { cierreDelExpediente, tituloDe } from "./agenda-texto";

interface Props {
  /** Las oportunidades que esperan confirmación; vacío = diálogo cerrado. */
  items: readonly PipelineAgendaItem[];
  retirando: boolean;
  onCancelar: () => void;
  onConfirmar: (seleccion: readonly PipelineAgendaItem[]) => void;
}

/** Por qué ya no admite oferta: la licitación se resolvió, o el plazo pasó. */
function porQue(item: PipelineAgendaItem): string {
  const cierre = cierreDelExpediente(item);
  if (cierre) return cierre;
  return item.due_date ? `Plazo: ${formatDate(item.due_date)}` : "Sin fecha límite";
}

function Fila({
  item,
  marcada,
  onAlternar,
}: {
  item: PipelineAgendaItem;
  marcada: boolean;
  onAlternar: () => void;
}) {
  const tituloId = React.useId();
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Checkbox
        checked={marcada}
        onCheckedChange={onAlternar}
        aria-labelledby={tituloId}
        className="mt-0.5 h-3.5 w-3.5"
      />
      <div className="min-w-0 flex-1">
        <span id={tituloId} className="block text-tf-meta">
          {tituloDe(item)}
        </span>
        <span className="block text-tf-micro text-muted-foreground">{porQue(item)}</span>
      </div>
    </li>
  );
}

function Confirmacion({ items, retirando, onCancelar, onConfirmar }: Props) {
  const varias = items.length > 1;
  // Se guarda lo que se **deja fuera**: el punto de partida es retirarlas todas.
  const [fuera, setFuera] = React.useState<ReadonlySet<string>>(new Set());
  const seleccion = items.filter((item) => !fuera.has(claveDe(item)));

  const alternar = (item: PipelineAgendaItem) => {
    const clave = claveDe(item);
    setFuera((previo) => {
      const siguiente = new Set(previo);
      if (siguiente.has(clave)) siguiente.delete(clave);
      else siguiente.add(clave);
      return siguiente;
    });
  };

  const unica = items[0];

  return (
    <Dialog open onOpenChange={(abierto) => (abierto ? undefined : onCancelar())}>
      <DialogContent className="w-[460px] max-w-[calc(100vw-2rem)] p-5">
        <DialogTitle>
          {varias ? "Retirar como no presentadas" : "Retirar como no presentada"}
        </DialogTitle>
        <DialogDescription className="mt-1 mb-4">
          {varias
            ? "Desmarca la que sí se presentó: se queda en la agenda, para registrarla en su ficha."
            : tituloDe(unica)}
        </DialogDescription>

        {varias && (
          <ul className="mb-4 max-h-[40vh] divide-y divide-border/40 overflow-y-auto">
            {items.map((item) => (
              <Fila
                key={claveDe(item)}
                item={item}
                marcada={!fuera.has(claveDe(item))}
                onAlternar={() => alternar(item)}
              />
            ))}
          </ul>
        )}

        <p className="mb-4 text-tf-meta text-muted-foreground">
          {varias
            ? "Se cierran como retiradas, con el motivo «No presentada», y salen de la agenda. No se pueden reabrir."
            : `${
                cierreDelExpediente(unica)
                  ? "La licitación ya está resuelta"
                  : `El plazo de presentación pasó${unica.due_date ? ` el ${formatDate(unica.due_date)}` : ""}`
              }. La oportunidad se cierra como retirada, con el motivo «No presentada», y sale de la agenda. No se puede reabrir.`}
        </p>

        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancelar}>
            Cancelar
          </Button>
          {/* «Retirar» y no «Cerrar»: la X del diálogo ya se anuncia así, y dos
              botones con el mismo nombre y sentidos opuestos es justo lo que
              oye quien navega con lector de pantalla. */}
          <Button
            size="sm"
            disabled={retirando || seleccion.length === 0}
            onClick={() => onConfirmar(seleccion)}
          >
            {retirando
              ? "Retirando…"
              : varias && seleccion.length > 0
                ? `Retirar ${formatNumber(seleccion.length)}`
                : "Retirar"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function RetirarNoPresentada(props: Props) {
  if (props.items.length === 0) return null;
  // `key` por lo que se pide retirar: cada apertura parte de todas marcadas,
  // sin un efecto que resincronice la selección.
  return <Confirmacion key={props.items.map(claveDe).join("|")} {...props} />;
}
