"use client";

/**
 * Piezas de presentación de la ficha de empresa.
 *
 * Salieron de `empresa-perfil.tsx` cuando ese fichero llegó a 333 líneas y el
 * límite `max-lines` de `eslint.config.mjs` (S7.1 del plan 2026-09 v2) lo dejó
 * en rojo. La frontera no es arbitraria: aquí queda lo que solo sabe pintar
 * —no consulta nada, no tiene estado y recibe todo por props— y allí se queda
 * la ficha, que es quien compone y decide.
 *
 * Se exportan porque las importa su hermano, no porque sean API de nadie más.
 */

import * as React from "react";
import { SectionTitle } from "@/components/console/panel";

export function Separador({ text }: { text: string }) {
  return (
    <>
      <span className="text-muted-foreground/60">·</span>
      <span>{text}</span>
    </>
  );
}

export function Relacionadas({
  title,
  items,
  onOpen,
}: {
  title: string;
  items: { empresa_id: number; nombre_canonico: string }[];
  onOpen: (empresaId: number) => void;
}) {
  return (
    <div className="min-w-0">
      <SectionTitle as="h3">{title}</SectionTitle>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <button
            key={item.empresa_id}
            type="button"
            onClick={() => onOpen(item.empresa_id)}
            className="tf-pressable border-border/70 text-tf-meta text-foreground hover:border-primary/50 inline-flex h-6.5 items-center rounded-md border px-2.5 font-medium"
          >
            {item.nombre_canonico}
          </button>
        ))}
      </div>
    </div>
  );
}
