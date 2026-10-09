"use client";

/**
 * Confirmar que una oportunidad con el plazo pasado **no se presentó**.
 *
 * Es el único gesto de la agenda sin deshacer: `withdrawn` es un estado terminal
 * y la API no reabre, así que aquí sí hay diálogo — a diferencia de completar
 * una tarea o descartar una señal, que se deshacen desde el aviso.
 *
 * No pregunta el motivo, como hace el cierre del tablero: lo que el botón
 * afirma («No nos presentamos») **es** el motivo, `no_presentada` en la lista
 * cerrada de D37. Hacerlo elegir en un desplegable sería pedir dos veces lo
 * mismo. Quien se retiró por otra causa —precio, solvencia— la registra desde
 * la ficha, donde está la lista entera.
 */

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { formatDate } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { tituloDe } from "./agenda-texto";

export function RetirarNoPresentada({
  item,
  retirando,
  onCancelar,
  onConfirmar,
}: {
  item: PipelineAgendaItem | null;
  retirando: boolean;
  onCancelar: () => void;
  onConfirmar: () => void;
}) {
  if (!item) return null;

  return (
    <Dialog open onOpenChange={(abierto) => (abierto ? undefined : onCancelar())}>
      <DialogContent className="w-[440px] max-w-[calc(100vw-2rem)] p-5">
        <DialogTitle>Retirar como no presentada</DialogTitle>
        <DialogDescription className="mt-1 mb-4">{tituloDe(item)}</DialogDescription>

        <p className="mb-4 text-tf-meta text-muted-foreground">
          El plazo de presentación pasó{item.due_date ? ` el ${formatDate(item.due_date)}` : ""}. La
          oportunidad se cierra como retirada, con el motivo «No presentada», y sale de la agenda.
          No se puede reabrir.
        </p>

        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancelar}>
            Cancelar
          </Button>
          {/* «Retirar» y no «Cerrar»: la X del diálogo ya se anuncia así, y dos
              botones con el mismo nombre y sentidos opuestos es justo lo que
              oye quien navega con lector de pantalla. */}
          <Button size="sm" disabled={retirando} onClick={onConfirmar}>
            {retirando ? "Retirando…" : "Retirar"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
