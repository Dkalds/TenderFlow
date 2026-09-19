"use client";

import { Star } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Pista } from "@/components/ui/pista";
import { StatusBadge } from "@/components/ui/status-badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { bandColor, shortEur } from "../../radar/_components/radar-shared";
import { useMetaFilters } from "@/hooks/use-meta-filters";
import { resolverCodigo } from "@/lib/procedimientos";
import type { MergedRow } from "../_hooks/detalle-table-model";

/**
 * F1.7 — procedimiento legible, con la tramitación y la definición en la
 * `Pista`. Sin `?` por fila: serían veinticinco paradas de tabulación más
 * dentro de filas que ya son focusables; la definición entera está en la
 * ficha. Un código sin catalogar se ve tal cual, con su aviso en el texto.
 */
function ProcedimientoCelda({
  procedimiento,
  tramitacion,
}: {
  procedimiento: string | null | undefined;
  tramitacion: string | null | undefined;
}) {
  const { data: meta } = useMetaFilters();
  const proc = resolverCodigo(meta, "procedimiento", procedimiento);
  const tram = resolverCodigo(meta, "tramitacion", tramitacion);
  if (!proc) return <span className="text-muted-foreground">—</span>;
  const texto = proc.catalogado ? proc.etiqueta : `${proc.codigo} (código no catalogado)`;
  const pista = [
    proc.descripcion,
    tram ? `Tramitación: ${tram.catalogado ? tram.etiqueta : `${tram.codigo} (no catalogada)`}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Pista contenido={pista || null}>
      <span className="block truncate text-[11.5px] text-muted-foreground">{texto}</span>
    </Pista>
  );
}

/**
 * Una fila de la tabla de Detalle.
 *
 * Las catorce celdas en el mismo orden que declara `COLUMNS`: sin esa
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
        {/* El punto era solo color + `title`: ni el teclado ni el lector
            sabían que la fila era nueva. Ahora lo dice un texto `sr-only` y
            la `Pista` lo enseña al puntero, sin sumar una parada por fila. */}
        {row.isNew && (
          <Pista contenido="Publicada desde tu última visita">
            <span className="block h-1.5 w-1.5 rounded-full bg-[hsl(var(--info))]">
              <span className="sr-only">Publicada desde tu última visita</span>
            </span>
          </Pista>
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
          className="tf-pressable grid h-6 w-6 place-items-center rounded"
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
      {/* Título y órgano: el texto entero va en el DOM (lo recorta el CSS, así
          que el lector lo lee completo) y la `Pista` lo enseña al puntero. Un
          disparador focusable aquí serían 50 paradas de tabulación por página
          dentro de una fila que ya es focusable. */}
      <td className="px-1">
        <Pista contenido={row.titulo}>
          <span
            className={cn(
              "block truncate text-[12.5px] leading-[1.3] tracking-[-0.005em]",
              open ? "font-semibold text-foreground" : "font-medium",
            )}
          >
            {row.titulo}
          </span>
        </Pista>
      </td>
      <td className="px-1">
        <Pista contenido={row.organo_contratacion}>
          <span className="block truncate text-xs leading-[1.3] text-muted-foreground">
            {row.organo_contratacion ?? ""}
          </span>
        </Pista>
      </td>
      <td className="tf-tnum px-1 text-right font-mono text-xs font-semibold">
        {compact ? shortEur(row.importe) : formatCurrency(row.importe)}
      </td>
      <td className="px-1">
        <StatusBadge value={row.estado} kind="estado" className="text-[10.5px]" />
      </td>
      <td className="px-1">
        <ProcedimientoCelda procedimiento={row.procedimiento} tramitacion={row.tramitacion} />
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
