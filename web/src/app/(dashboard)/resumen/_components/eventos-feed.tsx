"use client";

import Link from "next/link";
import {
  Activity,
  ArrowRightLeft,
  CalendarClock,
  FileCheck,
  type LucideIcon,
  RefreshCw,
  Scale,
  Trophy,
  XCircle,
} from "lucide-react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { formatCurrency, formatDate, truncate } from "@/lib/utils";
import type { EventosFeedResult } from "@/lib/api-types";

const TIPO_ICON: Record<string, LucideIcon> = {
  adjudicacion: Trophy,
  formalizacion: FileCheck,
  modificacion: RefreshCw,
  prorroga: CalendarClock,
  anulacion: XCircle,
  cambio_estado: ArrowRightLeft,
  recurso: Scale,
};

const TIPO_LABEL: Record<string, string> = {
  adjudicacion: "Adjudicación",
  formalizacion: "Formalización",
  modificacion: "Modificación",
  prorroga: "Prórroga",
  anulacion: "Anulación",
  cambio_estado: "Cambio de estado",
  recurso: "Recurso",
};

const MAX_FILAS = 8;

/**
 * Variación del importe del contrato.
 *
 * Iba en rojo cuando subía y en verde cuando bajaba, con `text-red-600` /
 * `text-green-400` a pelo — fuera del sistema de tokens y, peor, emitiendo un
 * juicio que el dato no contiene: que un contrato del mercado crezca no es malo
 * para quien mira el mercado. Queda el signo, que es lo que sí dice el dato.
 */
function ImporteDelta({ value }: { value: number | null | undefined }) {
  if (value == null || value === 0) return null;
  return (
    <span
      title="Variación del importe del contrato"
      className="tf-tnum flex-none font-mono text-[10.5px] font-semibold"
    >
      {value > 0 ? "+" : ""}
      {formatCurrency(value)}
    </span>
  );
}

/** Ventana del feed en palabras, para que el panel diga qué está midiendo
 * cuando el ámbito mueve las fechas. */
function ventanaLabel(desde: string | null, hasta: string | null): string {
  if (desde && hasta) return `Del ${formatDate(desde)} al ${formatDate(hasta)}`;
  if (desde) return `Desde el ${formatDate(desde)}`;
  if (hasta) return `Hasta el ${formatDate(hasta)}`;
  return "Últimos 30 días";
}

/** Feed de movimientos de contrato (prórrogas, modificaciones, anulaciones…)
 * — GET /api/v1/eventos.
 *
 * Es el único panel del Resumen que aplica **los siete** filtros del ámbito:
 * las fechas acotan aquí *el movimiento* (cuándo cambió el contrato), no la
 * publicación del expediente — ver el docstring de `GET /eventos`.
 *
 * Vestía todavía la `Card` heredada (título de 16 px, filas de 14) en una
 * pantalla cuyo resto está a 11 px: era el bloque que delataba que la página
 * venía de dos generaciones distintas. Ahora usa el vocabulario de panel de la
 * consola, como el resto.
 */
export function EventosFeed() {
  const { rango } = useFilters();
  const { data, isLoading, error, refetch } = useFilteredQuery<EventosFeedResult>(
    ["eventos", "feed"],
    "/api/v1/eventos",
    { staleTime: 2 * 60 * 1000 },
    { dias: "30", limit: "20" },
  );

  const items = data?.items ?? [];
  const visibles = items.slice(0, MAX_FILAS);

  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar los movimientos"
        detail={(error as Error).message}
        onRetry={() => void refetch()}
        height={220}
      />
    );
  }

  return (
    <Panel className="mb-5.5">
      <PanelTitle
        title="Movimientos del mercado"
        hint={`${ventanaLabel(rango.desde, rango.hasta)} · prórrogas, modificaciones y adjudicaciones del ámbito`}
        actions={
          items.length > visibles.length ? (
            <span className="tf-tnum text-muted-foreground font-mono text-[10.5px]">
              {visibles.length} de {items.length}
            </span>
          ) : undefined
        }
      />

      {isLoading ? (
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-7 w-full rounded" />
          ))}
        </div>
      ) : visibles.length === 0 ? (
        <PanelEmpty message="Ningún contrato del ámbito se ha movido en la ventana." />
      ) : (
        <ul>
          {visibles.map((evento, indice) => {
            const Icon = TIPO_ICON[evento.tipo] ?? Activity;
            return (
              <li key={`${evento.licitacion_id}-${evento.tipo}-${indice}`}>
                <Link
                  href={`/detalle?lic=${encodeURIComponent(evento.licitacion_id)}`}
                  className="border-border/25 hover:bg-primary/4 flex items-center gap-2.5 border-b px-1 py-1.5 transition-colors duration-140 ease-out last:border-b-0"
                >
                  <Icon
                    className="text-muted-foreground h-3.5 w-3.5 flex-none"
                    aria-hidden="true"
                  />
                  <span className="w-[104px] flex-none truncate text-[11px] font-semibold">
                    {TIPO_LABEL[evento.tipo] ?? evento.tipo}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[11.5px]">
                    {truncate(evento.titulo ?? evento.licitacion_id, 70)}
                  </span>
                  <ImporteDelta value={evento.importe_delta} />
                  <span className="text-muted-foreground tf-tnum w-[74px] flex-none text-right font-mono text-[10.5px]">
                    {evento.fecha ? formatDate(evento.fecha) : ""}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
