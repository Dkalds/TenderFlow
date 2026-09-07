"use client";

import * as React from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import type { RadarTender } from "@/hooks/use-radar";
import type { ModoInspector } from "../_hooks/use-media-query";
import { RadarInspector } from "./radar-inspector";

/**
 * Dónde vive el inspector, según el ancho.
 *
 * - **≥ xl — anclado.** Sus 432 px conviven con la lista, y el panel sigue a la
 *   selección: recorrer con J/K es leer el detalle de cada fila sin ningún
 *   gesto extra.
 * - **md–xl — `Sheet`.** No caben dos superficies a la vez, pero sí una encima.
 *   No se abre solo al seleccionar —eso convertiría cada J/K en un panel que
 *   tapa la lista—: se abre con «Ver ficha», el disparador que las acciones de
 *   la fila añaden justo en esta franja.
 * - **< md — nada.** Lo accionable ya baja entero a la ficha (seguir, descartar
 *   y abrir), así que lo que falta es contexto de lectura, y a 375 px un panel
 *   lateral o tapa la lista o la parte en dos. Ese contexto tiene pantalla
 *   propia en `/detalle?lic=`, enlazada desde el título del inspector.
 */
export function RadarInspectorPanel({
  modo,
  tender,
  followed,
  opening,
  abierta,
  onAbiertaChange,
  onFollow,
  onDismiss,
  onOpenPursuit,
}: {
  modo: ModoInspector;
  tender: RadarTender | undefined;
  followed: boolean;
  opening: boolean;
  abierta: boolean;
  onAbiertaChange: (abierta: boolean) => void;
  onFollow: () => void;
  onDismiss: () => void;
  onOpenPursuit: () => void;
}) {
  // Ensanchar la ventana hasta `xl` ancla el inspector: dejar el Sheet marcado
  // como abierto haría que volver a estrecharla lo resucitara sin que nadie lo
  // pidiera.
  React.useEffect(() => {
    if (modo !== "sheet" && abierta) onAbiertaChange(false);
  }, [modo, abierta, onAbiertaChange]);

  const contenido = tender ? (
    <RadarInspector
      key={tender.id_externo}
      tender={tender}
      followed={followed}
      onFollow={onFollow}
      onDismiss={onDismiss}
      onOpenPursuit={onOpenPursuit}
      opening={opening}
    />
  ) : null;

  return (
    <>
      <aside className="hidden w-[432px] flex-none flex-col bg-card/40 xl:flex">
        {contenido ?? (
          <div className="flex flex-1 items-center justify-center px-8 text-center">
            <p className="text-[13px] leading-[1.5] text-muted-foreground">
              Selecciona una señal para ver su desglose de score, sus fechas y quién suele ganar en
              ese órgano.
            </p>
          </div>
        )}
      </aside>

      <Sheet open={modo === "sheet" && abierta && tender != null} onOpenChange={onAbiertaChange}>
        <SheetContent
          side="right"
          // `p-0` porque el inspector trae su propio ritmo de márgenes, y
          // `[&>button]:hidden` esconde la X que el Sheet pone en `right-4
          // top-4`: ahí ya está el score de la señal, y el inspector tiene su
          // propio cierre rotulado en español.
          className="flex w-[min(28rem,92vw)] flex-col gap-0 p-0 sm:max-w-none [&>button]:hidden"
          aria-describedby={undefined}
        >
          <SheetTitle className="sr-only">Ficha de la señal</SheetTitle>
          {tender && (
            <RadarInspector
              key={tender.id_externo}
              tender={tender}
              followed={followed}
              onFollow={onFollow}
              onDismiss={onDismiss}
              onOpenPursuit={onOpenPursuit}
              opening={opening}
              onClose={() => onAbiertaChange(false)}
            />
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
