import { Bell } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * El botón de la campana, sin Radix: lo comparten la campana real
 * (`notification-bell.tsx`) y el disparador provisional del marco
 * (`components/layout/menus-diferidos.tsx`), que tienen que verse y nombrarse
 * igual para que el cambio de uno a otro no se note.
 */

/** Refresco del distintivo con la pestaña a la vista. */
export const REFRESCO_CAMPANA_MS = 5 * 60_000;

/** La talla de la barra de ámbito (`icon-sm`), junto a «Exportar» y «Buscar». */
export const CLASE_DISPARADOR_CAMPANA = cn(buttonVariants({ variant: "ghost", size: "icon-sm" }), "relative");

export function etiquetaCampana(sinLeer: number): string {
  return `Notificaciones${sinLeer > 0 ? ` (${sinLeer} sin leer)` : ""}`;
}

/** El recuento es la señal de «hay algo nuevo», no un error: va en el primario, no en rojo. */
export function ContenidoDisparadorCampana({ sinLeer }: { sinLeer: number }) {
  return (
    <>
      <Bell aria-hidden="true" />
      {sinLeer > 0 && (
        <span
          aria-hidden="true"
          className="tf-tnum absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-tf-micro leading-none font-semibold text-primary-foreground"
        >
          {sinLeer > 99 ? "99+" : sinLeer}
        </span>
      )}
    </>
  );
}
