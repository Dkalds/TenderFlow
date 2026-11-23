"use client";

import { Info, Redo2, RotateCcw, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ExportarDiferido, VistasDiferidas } from "@/components/layout/menus-diferidos";
import { ScopeChip } from "@/components/layout/scope-chips";
import type { BarraAmbitoMovilProps } from "@/components/layout/scope-movil";

/**
 * La hoja del ámbito en móvil (`scope-movil.tsx`): lo mismo que la barra y el
 * popover de «+ Añadir» de escritorio, apilado de arriba abajo.
 *
 * - Arriba, el título con el recuento, y deshacer y rehacer.
 * - En medio, con su scroll: el aviso de filtros que la pantalla no aplica,
 *   los chips activos (se quitan con su aspa) y el editor.
 * - Abajo, fijo y al alcance del pulgar: vistas guardadas, exportar y «Ver»,
 *   que cierra. Los filtros se aplican al tocarlos, como en escritorio: «Ver»
 *   no confirma nada, solo vuelve a la pantalla.
 *
 * Sin la «X» de la hoja: medía 16 px en la esquina de arriba, la más lejos del
 * pulgar, y «Ver» y Esc ya cierran.
 */
export function HojaAmbito({
  open,
  onOpenChange,
  chips,
  recuento,
  outOfScopeCount,
  onClearOutOfScope,
  historial,
  editor,
  extraExport,
}: BarraAmbitoMovilProps & { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { canUndo, canRedo, undo, redo } = historial;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        aria-describedby={undefined}
        className="flex max-h-[85dvh] flex-col gap-0 rounded-t-xl p-0 md:hidden [&>button]:hidden"
      >
        <div className="border-divider flex flex-none items-center gap-2 border-b px-4 py-3">
          <SheetTitle className="font-display">Ámbito</SheetTitle>
          <span className="tf-tnum text-tf-meta text-muted-foreground">{recuento}</span>
          <span className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={undo}
              disabled={!canUndo}
              aria-label="Deshacer cambio de ámbito"
            >
              <Undo2 aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={redo}
              disabled={!canRedo}
              aria-label="Rehacer cambio de ámbito"
            >
              <Redo2 aria-hidden="true" />
            </Button>
          </span>
        </div>

        {/* `relative`, como toda caja con scroll de la consola. */}
        <div className="relative min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {outOfScopeCount > 0 && (
            <div className="bg-muted text-tf-meta text-muted-foreground flex items-start gap-2 rounded-md px-3 py-2">
              <Info className="mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden="true" />
              <span className="flex-1">
                {outOfScopeCount === 1
                  ? "1 filtro activo no aplica en esta pantalla."
                  : `${outOfScopeCount} filtros activos no aplican en esta pantalla.`}
              </span>
              <Button variant="ghost" size="sm" onClick={onClearOutOfScope}>
                <RotateCcw aria-hidden="true" />
                {outOfScopeCount === 1 ? "Quitarlo" : "Quitarlos"}
              </Button>
            </div>
          )}
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5" aria-label="Filtros activos" role="group">
              {chips.map((chip) => (
                <ScopeChip key={`${chip.key}-${chip.value}`} chip={chip} />
              ))}
            </div>
          )}
          {editor}
        </div>

        <div className="border-divider flex flex-none items-center gap-2 border-t px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <VistasDiferidas />
          <ExportarDiferido label="Exportar" extraParams={extraExport} />
          <Button className="ml-auto" onClick={() => onOpenChange(false)}>
            {recuento === "—" ? "Ver resultados" : `Ver ${recuento}`}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
