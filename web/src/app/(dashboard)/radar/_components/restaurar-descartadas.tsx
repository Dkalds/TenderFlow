"use client";

/**
 * Confirmar «Restaurar todas las descartadas».
 *
 * Es el único gesto del Radar que pasa por un diálogo: descartar una señal se
 * deshace desde su aviso, pero restaurarlas todas deshace semanas de triaje de
 * un clic. El diálogo da el recuento; el aviso que sale al confirmar trae
 * «Deshacer» (ver `confirmarRestaurarTodas` en `use-radar-consola.ts`).
 */

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { formatNumber } from "@/lib/utils";

interface Props {
  abierto: boolean;
  total: number;
  onCancelar: () => void;
  onConfirmar: () => void;
}

export function RestaurarDescartadas({ abierto, total, onCancelar, onConfirmar }: Props) {
  if (!abierto || total === 0) return null;
  const una = total === 1;
  return (
    <Dialog open onOpenChange={(sigue) => (sigue ? undefined : onCancelar())}>
      <DialogContent className="w-[420px] max-w-[calc(100vw-2rem)] p-5">
        <DialogTitle>{una ? "Restaurar la descartada" : "Restaurar las descartadas"}</DialogTitle>
        <DialogDescription className="mt-1 mb-4">
          {una
            ? "La señal que descartaste vuelve a la bandeja, con las demás por revisar."
            : `Las ${formatNumber(total)} señales que descartaste vuelven a la bandeja, con las demás por revisar.`}{" "}
          Tendrás unos segundos para deshacerlo desde el aviso.
        </DialogDescription>
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancelar}>
            Cancelar
          </Button>
          <Button size="sm" onClick={onConfirmar}>
            {una ? "Restaurar" : `Restaurar ${formatNumber(total)}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
