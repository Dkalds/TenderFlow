import { Skeleton } from "@/components/ui/skeleton";
import { SPACE_VIEWS } from "@/lib/space-views";
import { cn } from "@/lib/utils";

/**
 * Esqueleto de ruta de un espacio: la cabecera de `SpaceShell` y su cuerpo, con
 * las mismas cotas.
 *
 * Lo pinta el `loading.tsx` de la ruta mientras llega su RSC, y el relevo con
 * la página tiene que ser invisible: la cabecera mide lo mismo (h-11), el
 * cuerpo lleva el mismo relleno y, con `bleed`, el mismo borde duro. Hay una
 * pastilla por vista de `SPACE_VIEWS`, la tabla de la que sale el conmutador:
 * el esqueleto no promete ni una pestaña de más ni una de menos.
 *
 * Sin `"use client"` a propósito: lo usan `loading.tsx` de servidor, que así no
 * cargan JavaScript para pintarlo, y de cliente.
 */
export function SpaceShellEsqueleto({
  spaceKey,
  bleed,
  children,
}: {
  spaceKey: string;
  bleed?: boolean;
  children: React.ReactNode;
}) {
  const vistas = SPACE_VIEWS[spaceKey] ?? [];
  return (
    <div data-slot="space-shell-esqueleto" className="flex h-full min-h-0 flex-col">
      <div
        className={cn(
          "flex h-11 flex-none items-center gap-2.5 overflow-hidden px-4",
          bleed && "border-border/60 border-b",
        )}
      >
        <Skeleton className="h-4 w-24 rounded" />
        {/* La descripción del espacio sólo existe en `xl`; sin ella, las
            pestañas saltarían a la derecha al llegar la cabecera real. */}
        <Skeleton className="hidden h-3 w-56 rounded xl:block" />
        {vistas.length > 1 && (
          <div className="border-border/60 ml-2 flex items-center gap-0.5 border-l pl-2.5">
            {vistas.map((vista) => (
              <Skeleton key={vista.key} data-slot="pestana-esqueleto" className="h-7 w-16 rounded-md" />
            ))}
          </div>
        )}
      </div>
      <div className={cn("min-h-0 flex-1 overflow-hidden", !bleed && "px-4 pt-4 pb-6")}>{children}</div>
    </div>
  );
}

/**
 * Lo que pinta una vista de espacio mientras llega su chunk: el `loading` de
 * `next/dynamic` en las páginas de Mercado y Oportunidades. El `loading.tsx` de
 * ruta pinta el mismo, así que la vista aparece donde estaba su esqueleto.
 */
export function VistaEsqueleto() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-[320px] w-full rounded-xl" />
    </div>
  );
}
