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
 * El cajón de navegación de móvil del rail (`console-rail.tsx`).
 *
 * Módulo propio porque solo existe abierto: el rail lo monta la primera vez que
 * se pulsa «Abrir navegación», y con él Radix Dialog y el bloqueo de scroll
 * dejan de viajar en el First Load de cada pantalla del dashboard, también en
 * escritorio, donde el cajón no se abre nunca.
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
      <SheetContent side="left" className="w-72 overflow-y-auto p-3 md:hidden">
        <SheetTitle className="px-2 pb-2 text-tf-meta font-semibold text-muted-foreground">Espacios</SheetTitle>
        <nav aria-label="Navegación móvil" className="space-y-0.5">
          {groups.map((entry, index) => (
            <React.Fragment key={entry.group}>
              {index > 0 && <span className="bg-border/70 my-2 block h-px" aria-hidden="true" />}
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
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-tf-body font-medium transition-colors",
                      active
                        ? "bg-primary/10 text-foreground"
                        : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
                    )}
                  >
                    <Icon className={cn("h-4 w-4 shrink-0", active && "text-primary")} aria-hidden="true" />
                    {space.label}
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
