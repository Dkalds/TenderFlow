"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { landingHref, type ConsoleSpace } from "@/lib/console-spaces";
import { registrarEvento } from "@/lib/analytics";

export interface GrupoDeEspacios {
  group: ConsoleSpace["group"];
  items: ConsoleSpace[];
}

/**
 * La hoja «Más» de la barra inferior de móvil (`barra-inferior.tsx`): todos los
 * espacios, con los mismos grupos que el rail de escritorio.
 *
 * Sale de abajo, del mismo sitio que el botón que la abre, y no del borde
 * izquierdo: así el destino queda al alcance del mismo pulgar. Cada destino
 * mide 44 px de alto, la diana táctil.
 *
 * Módulo propio porque solo existe abierto: la barra lo monta la primera vez que
 * se pulsa «Más», y con él Radix Dialog y el bloqueo de scroll dejan de viajar
 * en el First Load de cada pantalla del dashboard, también en escritorio, donde
 * la hoja no se abre nunca.
 */
export function NavegacionMovil({
  open,
  onOpenChange,
  groups,
  activeKey,
  withFilters,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: readonly GrupoDeEspacios[];
  activeKey: string | undefined;
  withFilters: (href: string) => string;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="max-h-[85dvh] overflow-y-auto rounded-t-xl p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:hidden"
      >
        <SheetTitle className="px-2 pb-2 text-tf-meta font-semibold text-muted-foreground">Espacios</SheetTitle>
        <nav aria-label="Navegación móvil" className="grid grid-cols-2 gap-x-1 gap-y-0.5">
          {groups.map((entry, index) => (
            <React.Fragment key={entry.group}>
              {index > 0 && <span className="bg-divider col-span-2 my-1.5 block h-px" aria-hidden="true" />}
              {entry.items.map((space) => {
                const Icon = space.icon;
                const active = activeKey === space.key;
                return (
                  <Link
                    key={space.key}
                    href={withFilters(landingHref(space))}
                    // Mismo evento, distinto origen: el cajón móvil se usa
                    // sobre un diseño pensado para escritorio, y saber cuánto
                    // pesa es la mitad de la decisión de invertir en él.
                    onClick={() => {
                      registrarEvento("espacio_abierto", {
                        espacio: space.key,
                        origen: "rail_movil",
                      });
                      onOpenChange(false);
                    }}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 min-w-0 items-center gap-2.5 rounded-md px-3 text-tf-body font-medium transition-colors",
                      active
                        ? "bg-primary-selected text-foreground"
                        : "text-muted-foreground hover:bg-primary-hover hover:text-foreground",
                    )}
                  >
                    <Icon className={cn("h-4 w-4 shrink-0", active && "text-primary")} aria-hidden="true" />
                    <span className="truncate">{space.label}</span>
                  </Link>
                );
              })}
            </React.Fragment>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
