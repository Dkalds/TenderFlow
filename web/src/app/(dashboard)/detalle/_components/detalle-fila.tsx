"use client";

import { Star } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/ui/status-badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatCurrency, formatDate, truncate } from "@/lib/utils";
import { bandColor, shortEur } from "../../radar/_components/radar-shared";
import type { MergedRow } from "../_hooks/detalle-table-model";

/**
 * Una fila de la tabla de Detalle.
 *
 * Las trece celdas en el mismo orden que declara `COLUMNS`: sin esa
 * correspondencia el `<colgroup>` reparte anchos sobre columnas equivocadas.
 * Las dos celdas de cross-filter (CCAA y Tecnología) son botones y no texto
 * porque filtran; lo demás es dato.
 */
export function DetalleFila({
  row,
  index,
  open,
  picked,
  isCursor,
  favorite,
  ccaaOn,
  tecOn,
  compact,
  rowHeight,
  atenuada,
  onOpen,
  onToggleSelect,
  onToggleFavorite,
  onToggleCcaa,
  onToggleTecnologia,
}: {
  row: MergedRow;
  index: number;
  open: boolean;
  picked: boolean;
  isCursor: boolean;
  favorite: boolean;
  ccaaOn: boolean;
  tecOn: boolean;
  compact: boolean;
  rowHeight: number;
  /** Refetch en curso: la página anterior sigue en pantalla, atenuada. */
  atenuada: boolean;
  onOpen: (index: number, id: string) => void;
  onToggleSelect: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onToggleCcaa: (ccaa: string) => void;
  onToggleTecnologia: (tecnologia: string) => void;
}) {
  return (
    <tr
      data-detalle-row={isCursor ? "cursor" : undefined}
      tabIndex={0}
      aria-selected={picked}
      onClick={() => onOpen(index, row.id_externo)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(index, row.id_externo);
        }
      }}
      style={{ height: rowHeight }}
      className={cn(
        "relative cursor-pointer border-b border-border/30 transition-colors duration-110 ease-out",
        atenuada && "opacity-60",
        open ? "bg-primary/9" : picked ? "bg-primary/4" : "hover:bg-primary/5",
        isCursor && !open && "ring-1 ring-inset ring-primary/25",
      )}
    >
      <td className="relative px-1 pl-3.5">
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-0.5 transition-colors duration-110 ease-out"
          style={{ background: open ? bandColor(row.band) : "transparent" }}
        />
        <Checkbox
          className="h-3.5 w-3.5"
          aria-label={`Seleccionar ${row.titulo}`}
          checked={picked}
          onCheckedChange={() => onToggleSelect(row.id_externo)}
          onClick={(event) => event.stopPropagation()}
        />
      </td>
      <td>
        {row.isNew && (
          <span
            className="block h-1.5 w-1.5 rounded-full bg-[hsl(var(--info))]"
            title="Publicada desde tu última visita"
          />
        )}
      </td>
      <td>
        {/* Sin `Tooltip` a propósito: el `title` que había
            aquí no decía nada que no esté ya en pantalla —el
            atajo «S · favorito» vive en la tira de SHORTCUTS
            del pie— y el `aria-label` sí distingue añadir de
            quitar, que es lo que el `title` no hacía. De paso
            son 25 Popovers menos por página. */}
        <button
          type="button"
          aria-label={favorite ? "Quitar de favoritos" : "Añadir a favoritos"}
          aria-pressed={favorite}
          onClick={(event) => {
            event.stopPropagation();
            onToggleFavorite(row.id_externo);
          }}
          className="tf-pressable grid h-5 w-5 place-items-center rounded"
        >
          <Star
            className={cn(
              "h-3.5 w-3.5 transition-colors duration-140 ease-out",
              favorite ? "fill-primary text-primary" : "text-muted-foreground/45",
            )}
          />
        </button>
      </td>
      <td className="truncate px-1 font-mono text-[10.5px] text-muted-foreground">
        {row.id_externo.replace("PLACSP-", "")}
      </td>
      <td className="px-1">
        <span
          title={row.titulo}
          className={cn(
            "block truncate text-[12.5px] leading-[1.3] tracking-[-0.005em]",
            open ? "font-semibold text-foreground" : "font-medium",
          )}
        >
          {row.titulo}
        </span>
      </td>
      <td className="px-1">
        <span
          title={row.organo_contratacion ?? ""}
          className="block truncate text-xs leading-[1.3] text-muted-foreground"
        >
          {truncate(row.organo_contratacion, compact ? 30 : 40)}
        </span>
      </td>
      <td className="tf-tnum px-1 text-right font-mono text-xs font-semibold">
        {compact ? shortEur(row.importe) : formatCurrency(row.importe)}
      </td>
      <td className="px-1">
        <StatusBadge value={row.estado} kind="estado" className="text-[10.5px]" />
      </td>
      <td className="truncate px-1 align-middle whitespace-nowrap">
        <span
          className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle"
          style={{ background: bandColor(row.band) }}
          aria-hidden="true"
        />
        <span className="tf-tnum mr-1.5 font-mono text-xs font-semibold">
          {row.score != null ? Math.round(row.score) : "—"}
        </span>
        <span className="font-mono text-[9.5px] text-muted-foreground">{row.band ?? ""}</span>
      </td>
      <td className="tf-tnum px-1 text-right font-mono text-[10.5px] text-muted-foreground">
        {formatDate(row.fecha_publicacion)}
      </td>
      <td className="px-1">
        {row.ccaa ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`Filtrar por ${row.ccaa}`}
                aria-pressed={ccaaOn}
                onClick={(event) => {
                  event.stopPropagation();
                  onToggleCcaa(row.ccaa!);
                }}
                className={cn(
                  "block max-w-full truncate rounded px-1.5 py-0.5 text-left text-[11.5px] transition-colors duration-140 ease-out",
                  ccaaOn
                    ? "border border-primary/40 bg-primary/14 font-semibold text-primary"
                    : "border border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {row.ccaa}
              </button>
            </TooltipTrigger>
            <TooltipContent>{`Filtrar por ${row.ccaa}`}</TooltipContent>
          </Tooltip>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="truncate px-1 font-mono text-[10.5px] text-muted-foreground">
        {row.cpv ?? "—"}
      </td>
      <td className="px-1 pr-3.5">
        {row.tecnologia ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`Filtrar por ${row.tecnologia}`}
                aria-pressed={tecOn}
                onClick={(event) => {
                  event.stopPropagation();
                  onToggleTecnologia(row.tecnologia!);
                }}
                className={cn(
                  "block max-w-full truncate rounded border px-1.5 py-0.5 text-left text-[10.5px] font-medium transition-colors duration-140 ease-out",
                  tecOn
                    ? "border-[hsl(var(--info)/0.5)] bg-[hsl(var(--info)/0.2)] text-[hsl(var(--info))]"
                    : "border-[hsl(var(--info)/0.22)] bg-[hsl(var(--info)/0.08)] text-[hsl(var(--info))]",
                )}
              >
                {row.tecnologia}
              </button>
            </TooltipTrigger>
            <TooltipContent>{`Filtrar por ${row.tecnologia}`}</TooltipContent>
          </Tooltip>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
    </tr>
  );
}
