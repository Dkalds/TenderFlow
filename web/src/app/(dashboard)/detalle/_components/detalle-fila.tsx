"use client";

import { plazoVisual } from "@/components/pursuits/pursuit-presenters";
import { SeguirBoton } from "@/components/seguir-boton";
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
function Procedimiento({
  procedimiento,
  tramitacion,
}: {
  procedimiento: string | null | undefined;
  tramitacion: string | null | undefined;
}) {
  const { data: meta } = useMetaFilters();
  const proc = resolverCodigo(meta, "procedimiento", procedimiento);
  const tram = resolverCodigo(meta, "tramitacion", tramitacion);
  if (!proc) return null;
  const texto = proc.catalogado ? proc.etiqueta : `${proc.codigo} (código no catalogado)`;
  const pista = [
    proc.descripcion,
    tram ? `Tramitación: ${tram.catalogado ? tram.etiqueta : `${tram.codigo} (no catalogada)`}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Pista contenido={pista || null}>
      <span className="flex-none">{texto}</span>
    </Pista>
  );
}

/** Botón de filtro cruzado: CCAA y Tecnología filtran el ámbito al pulsarlos. */
function FiltroCruzado({
  valor,
  activo,
  onToggle,
  className,
}: {
  valor: string;
  activo: boolean;
  onToggle: (valor: string) => void;
  className: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`Filtrar por ${valor}`}
          aria-pressed={activo}
          onClick={(event) => {
            event.stopPropagation();
            onToggle(valor);
          }}
          className={className}
        >
          {valor}
        </button>
      </TooltipTrigger>
      <TooltipContent>{`Filtrar por ${valor}`}</TooltipContent>
    </Tooltip>
  );
}

const SEPARADOR = <span aria-hidden="true">·</span>;

/**
 * Una fila de la tabla de Detalle, en el orden de `COLUMNS`: sin esa
 * correspondencia el `<colgroup>` reparte anchos sobre columnas equivocadas.
 *
 * La celda «Licitación» reúne en tres líneas lo que antes eran seis columnas:
 * el título entero; órgano, CCAA y procedimiento; expediente, CPV y fecha de
 * publicación. Los dos filtros cruzados (CCAA y Tecnología) son botones porque
 * filtran; lo demás es dato.
 */
export function DetalleFila({
  row,
  index,
  open,
  picked,
  isCursor,
  ccaaOn,
  tecOn,
  compact,
  rowHeight,
  atenuada,
  onOpen,
  onToggleSelect,
  onToggleCcaa,
  onToggleTecnologia,
}: {
  row: MergedRow;
  index: number;
  open: boolean;
  picked: boolean;
  isCursor: boolean;
  ccaaOn: boolean;
  tecOn: boolean;
  compact: boolean;
  rowHeight: number;
  /** Refetch en curso: la página anterior sigue en pantalla, atenuada. */
  atenuada: boolean;
  onOpen: (index: number, id: string) => void;
  onToggleSelect: (id: string) => void;
  onToggleCcaa: (ccaa: string) => void;
  onToggleTecnologia: (tecnologia: string) => void;
}) {
  const plazo = plazoVisual(row.fecha_limite);
  const celda = compact ? "py-1" : "py-2";
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
        "relative cursor-pointer border-b border-divider-subtle align-top transition-colors duration-110 ease-out",
        atenuada && "opacity-60",
        open ? "bg-primary-selected" : picked ? "bg-primary-hover" : "hover:bg-primary-hover",
        // Pulsado de la fila, salvo cuando lo pulsado es la casilla, «Seguir» o
        // un filtro: `:active` sube a los ancestros. Llega sin transición y se
        // va con la de la fila.
        !open && "[&:active:not(:has(button:active))]:bg-primary-selected [&:active:not(:has(button:active))]:duration-0",
        isCursor && !open && "ring-1 ring-inset ring-primary-line",
      )}
    >
      <td className={cn("relative px-1 pl-3.5", celda)}>
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-0.5 transition-colors duration-110 ease-out"
          style={{ background: open ? bandColor(row.band) : "transparent" }}
        />
        <Checkbox
          className="mt-0.5 h-3.5 w-3.5"
          aria-label={`Seleccionar ${row.titulo}`}
          checked={picked}
          onCheckedChange={() => onToggleSelect(row.id_externo)}
          onClick={(event) => event.stopPropagation()}
        />
      </td>
      <td className={celda}>
        <div className="flex items-center gap-1">
          {/* El punto lo dice un texto `sr-only` y la `Pista` lo enseña al
              puntero, sin sumar una parada de tabulación por fila. */}
          <span className="grid w-1.5 flex-none place-items-center">
            {row.isNew && (
              <Pista contenido="Publicada desde tu última visita">
                <span className="block h-1.5 w-1.5 rounded-full bg-info">
                  <span className="sr-only">Publicada desde tu última visita</span>
                </span>
              </Pista>
            )}
          </span>
          {/* El control único de ADR-031 §C (el mismo del Radar), con la piel
              y los nombres accesibles de siempre de esta tabla. */}
          <SeguirBoton
            targetType="licitacion"
            targetId={row.id_externo}
            variante="icono"
            icono="estrella"
            nombreAccesible={{ seguir: "Añadir a favoritos", dejar: "Quitar de favoritos" }}
            clases={{
              base: "tf-pressable grid h-6 w-6 place-items-center rounded-md",
              activo: "text-primary",
              inactivo: "text-muted-foreground/45",
            }}
          />
        </div>
      </td>
      <td className={cn("min-w-0 px-1", celda)}>
        {/* El texto entero va en el DOM (lo recorta el CSS, así que el lector
            lo lee completo) y la `Pista` lo enseña al puntero. */}
        <Pista contenido={row.titulo}>
          <span
            className={cn(
              "block text-tf-body leading-snug text-pretty",
              compact ? "truncate" : "line-clamp-2",
              open ? "font-semibold text-foreground" : "font-medium",
            )}
          >
            {row.titulo}
          </span>
        </Pista>
        <div className="mt-0.5 flex min-w-0 items-baseline gap-1.5 text-tf-meta text-muted-foreground">
          {row.organo_contratacion && (
            <Pista contenido={row.organo_contratacion}>
              <span className="min-w-0 truncate">{row.organo_contratacion}</span>
            </Pista>
          )}
          {row.organo_contratacion && row.ccaa && SEPARADOR}
          {row.ccaa && (
            <FiltroCruzado
              valor={row.ccaa}
              activo={ccaaOn}
              onToggle={onToggleCcaa}
              className={cn(
                "flex-none rounded-sm px-0.5 transition-colors",
                ccaaOn ? "bg-primary-selected font-medium text-primary" : "hover:text-foreground",
              )}
            />
          )}
          {row.procedimiento && (row.organo_contratacion || row.ccaa) && SEPARADOR}
          <Procedimiento procedimiento={row.procedimiento} tramitacion={row.tramitacion} />
        </div>
        <div className="tf-tnum mt-0.5 flex min-w-0 items-baseline gap-1.5 font-mono text-tf-micro text-muted-foreground">
          {/* El número de expediente, no la clave: `expediente` es el id sin
              prefijo de fuente ni órgano (fase A del RFC de identidad PLACSP). */}
          <span className="min-w-0 truncate">{row.expediente ?? row.id_externo}</span>
          {row.cpv && (
            <>
              {SEPARADOR}
              <span className="flex-none">CPV {row.cpv}</span>
            </>
          )}
          {row.fecha_publicacion && (
            <>
              {SEPARADOR}
              <span className="flex-none">pub. {formatDate(row.fecha_publicacion)}</span>
            </>
          )}
        </div>
      </td>
      <td className={cn("px-1", celda)}>
        {row.tecnologia ? (
          <FiltroCruzado
            valor={row.tecnologia}
            activo={tecOn}
            onToggle={onToggleTecnologia}
            className={cn(
              "block max-w-full truncate rounded-md border px-1.5 py-0.5 text-left text-tf-micro font-medium text-info transition-colors",
              tecOn ? "border-info/50 bg-info/15" : "border-info/30 bg-info/10",
            )}
          />
        ) : row.ml_tech_principal ? (
          // Sin término del diccionario, la etiqueta del clasificador. No es
          // filtro cruzado: el filtro de tecnología busca en el diccionario y
          // con ella devolvería cero filas. El borde discontinuo la distingue.
          <Pista contenido="Tecnología estimada">
            <span className="block max-w-full truncate rounded-md border border-dashed border-info/30 px-1.5 py-0.5 text-tf-micro font-medium text-info">
              {row.ml_tech_principal}
              <span className="sr-only"> (estimada)</span>
            </span>
          </Pista>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className={cn("tf-tnum px-1 text-right text-tf-meta font-semibold", celda)}>
        {compact ? shortEur(row.importe) : formatCurrency(row.importe)}
      </td>
      <td className={cn("px-1", celda)}>
        {row.fecha_limite ? (
          <>
            <span className="tf-tnum block text-tf-meta">{formatDate(row.fecha_limite)}</span>
            {plazo && <span className={cn("block text-tf-micro font-medium", plazo.clases.texto)}>{plazo.texto}</span>}
          </>
        ) : (
          <span className="text-tf-meta text-muted-foreground">Sin fecha</span>
        )}
      </td>
      <td className={cn("px-1", celda)}>
        <StatusBadge value={row.estado} kind="estado" className="text-tf-micro" />
      </td>
      <td className={cn("truncate px-1 pr-3.5 whitespace-nowrap", celda)}>
        <span
          className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle"
          style={{ background: bandColor(row.band) }}
          aria-hidden="true"
        />
        <span className="tf-tnum mr-1.5 text-tf-meta font-semibold">
          {row.score != null ? Math.round(row.score) : "—"}
        </span>
        <span className="text-tf-micro text-muted-foreground">{row.band ?? ""}</span>
      </td>
    </tr>
  );
}
