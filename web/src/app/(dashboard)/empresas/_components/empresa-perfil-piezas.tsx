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
import { TrendingDown, TrendingUp } from "lucide-react";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

export function Separador({ text }: { text: string }) {
  return (
    <>
      <span className="text-muted-foreground/60">·</span>
      <span>{text}</span>
    </>
  );
}

export function SubTitulo({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center gap-2.5">
      <h3 className="text-tf-micro text-muted-foreground font-mono font-semibold tracking-[0.1em] uppercase">
        {children}
      </h3>
      {aside}
    </div>
  );
}

export function Total({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="border-border/60 min-w-0 rounded-[10px] border px-3.5 py-3">
      <div className="text-tf-meta text-muted-foreground mb-2.5">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className="tf-tnum text-tf-title font-mono font-semibold">{value}</span>
        {sub && <span className="text-tf-meta text-muted-foreground">{sub}</span>}
      </div>
    </div>
  );
}

/**
 * Trayectoria por año: la altura es el importe, la cifra son los contratos.
 *
 * A 120px de alto y con la cifra a 11px se lee; a 92 con la cifra a 9,5 no.
 * Y el año va completo (2021, no «21»): abreviarlo no ahorraba ni el ancho de
 * una barra.
 */
export function Trayectoria({ anios }: { anios: { anio: number; contratos: number; importe: number }[] }) {
  const maximo = Math.max(...anios.map((a) => a.importe), 1);
  const primero = anios[0]?.importe ?? 0;
  const ultimoCompleto = anios[Math.max(0, anios.length - 2)]?.importe ?? 0;
  const creciendo = ultimoCompleto >= primero;
  const Icono = creciendo ? TrendingUp : TrendingDown;

  return (
    <>
      <SubTitulo
        aside={
          <>
            <span
              className={cn(
                "text-tf-meta inline-flex items-center gap-1.5 font-medium",
                creciendo ? "text-[hsl(var(--success))]" : "text-destructive",
              )}
            >
              <Icono className="h-3 w-3" aria-hidden="true" />
              {creciendo ? "en crecimiento" : "en declive"}
            </span>
            <span className="flex-1" />
          </>
        }
      >
        Trayectoria por año
      </SubTitulo>
      <div className="border-border/60 relative mb-6 flex h-[120px] items-end gap-2.5 border-b pb-5">
        {anios.map((anio) => (
          <div key={anio.anio} className="relative flex h-full flex-1 flex-col items-center justify-end gap-1.5">
            <span className="tf-tnum text-tf-micro text-muted-foreground font-mono font-medium">
              {formatNumber(anio.contratos)}
            </span>
            <span
              className="bg-primary/70 block min-h-[2px] w-full rounded-t-[3px]"
              style={{ height: `${(anio.importe / maximo) * 100}%` }}
              title={`${anio.anio}: ${formatNumber(anio.contratos)} contratos · ${formatCurrency(anio.importe)}`}
            />
            <span className="text-tf-micro text-muted-foreground absolute -bottom-[18px] font-mono">{anio.anio}</span>
          </div>
        ))}
      </div>
    </>
  );
}

export function Ranking({
  title,
  rows,
  className,
}: {
  title: string;
  rows: { label: string; contratos: number; importe: number }[];
  className?: string;
}) {
  const maximo = Math.max(...rows.map((r) => r.contratos), 1);
  return (
    <div className={cn("min-w-0", className)}>
      <SubTitulo>{title}</SubTitulo>
      {rows.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">Sin datos.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.slice(0, 6).map((row) => (
            <div key={row.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
              <span className="flex min-w-0 items-center gap-2.5">
                <span
                  className="bg-primary/55 h-1 flex-none rounded-sm"
                  style={{ width: `${Math.max(4, (row.contratos / maximo) * 40)}px` }}
                />
                <span className="text-tf-body text-muted-foreground min-w-0 truncate">{row.label}</span>
              </span>
              <span className="tf-tnum text-tf-meta text-muted-foreground font-mono font-medium whitespace-nowrap">
                {formatNumber(row.contratos)} · {formatCurrency(row.importe)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
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
      <SubTitulo>{title}</SubTitulo>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <button
            key={item.empresa_id}
            type="button"
            onClick={() => onOpen(item.empresa_id)}
            className="tf-pressable border-border/70 text-tf-meta text-foreground hover:border-primary/50 inline-flex h-6.5 items-center rounded-md border px-2.5 font-medium transition-colors"
          >
            {item.nombre_canonico}
          </button>
        ))}
      </div>
    </div>
  );
}
