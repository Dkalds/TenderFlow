"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Los dos ladrillos del inspector: el rótulo de sección y el dato suelto.
 *
 * Viven aparte porque los comparten el cuerpo del inspector y el bloque de
 * competencia esperada, y su tamaño de letra —9,5 px en versalita para el
 * rótulo, 8,5 px para la etiqueta del dato— es lo que da al panel su densidad.
 * Si cada bloque los redefiniera, el panel dejaría de leerse como una rejilla.
 */

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-baseline justify-between">
      <h3 className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {children}
      </h3>
      {aside}
    </div>
  );
}

export function Fact({
  label,
  value,
  variant = "text",
  color,
}: {
  label: string;
  value: React.ReactNode;
  variant?: "text" | "mono";
  color?: string;
}) {
  return (
    <div className="bg-card px-3 py-2.5">
      <div className="mb-1.5 font-mono text-[8.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          variant === "mono"
            ? "tf-tnum font-mono text-[13px] font-semibold leading-tight"
            : "text-[12.5px] font-medium leading-snug",
        )}
        style={color ? { color } : undefined}
      >
        {value}
      </div>
    </div>
  );
}
