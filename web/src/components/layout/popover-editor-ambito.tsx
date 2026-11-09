"use client";

import * as React from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type MontajeDiferido, useMontajeDiferido } from "@/components/ui/carga-diferida";
import { BotonAnadir } from "@/components/layout/scope-barras";

/**
 * El popover de «+ Añadir» con el editor del ámbito dentro. La barra lo monta
 * diferido (`scope-barras.tsx`) y su apertura la gobierna `scope-bar.tsx`: si
 * se pulsó el disparador provisional, llega pidiendo abrirse.
 */
export function PopoverEditorAmbito({
  open,
  onOpenChange,
  onAcercarse,
  editor,
  ...montaje
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Puntero o foco sobre «+ Añadir»: el editor está a punto de abrirse. */
  onAcercarse: () => void;
  editor: React.ReactNode;
} & MontajeDiferido) {
  const { disparador, abiertoAlMontar } = useMontajeDiferido(montaje);
  React.useEffect(() => {
    if (abiertoAlMontar) onOpenChange(true);
  }, [abiertoAlMontar, onOpenChange]);

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <BotonAnadir ref={disparador} onPointerEnter={onAcercarse} onFocus={onAcercarse} />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        {editor}
      </PopoverContent>
    </Popover>
  );
}
