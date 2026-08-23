"use client";

import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Activity,
  Trophy,
  FileCheck,
  RefreshCw,
  CalendarClock,
  XCircle,
  ArrowRightLeft,
  Scale,
  type LucideIcon,
} from "lucide-react";
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

function ImporteDelta({ value }: { value: number | null | undefined }) {
  if (value == null || value === 0) return null;
  const positive = value > 0;
  return (
    <span
      className={
        positive
          ? "text-red-600 dark:text-red-400"
          : "text-green-600 dark:text-green-400"
      }
    >
      {positive ? "+" : ""}
      {formatCurrency(value)}
    </span>
  );
}

/** Ventana del feed en palabras, para que la tarjeta diga qué está midiendo
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
 * Lee por el ámbito global como el resto del Resumen: un panel que ignoraba
 * los filtros mientras los KPIs de arriba los respetaban contaba movimientos
 * de expedientes que la pantalla ya había descartado. Las fechas del ámbito
 * acotan aquí *el movimiento* (cuándo cambió el contrato), no la publicación
 * del expediente — ver el docstring de `GET /eventos`. */
export function EventosFeed() {
  const { rango } = useFilters();
  const { data, isLoading } = useFilteredQuery<EventosFeedResult>(
    ["eventos", "feed"],
    "/api/v1/eventos",
    { staleTime: 2 * 60 * 1000 },
    { dias: "30", limit: "20" },
  );

  const items = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4" />
          Movimientos del pipeline
        </CardTitle>
        <CardDescription>
          {ventanaLabel(rango.desde, rango.hasta)} — prórrogas, modificaciones y
          adjudicaciones del ámbito activo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="space-y-1">
            {items.map((ev, i) => {
              const Icon = TIPO_ICON[ev.tipo] ?? Activity;
              return (
                <li key={`${ev.licitacion_id}-${ev.tipo}-${i}`}>
                  <Link
                    href={`/detalle?lic=${encodeURIComponent(ev.licitacion_id)}`}
                    className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted/50"
                  >
                    <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="font-medium">
                          {TIPO_LABEL[ev.tipo] ?? ev.tipo}
                        </span>
                        <ImporteDelta value={ev.importe_delta} />
                      </span>
                      <span className="block truncate text-muted-foreground">
                        {truncate(ev.titulo ?? ev.licitacion_id, 70)}
                      </span>
                      {ev.fecha && (
                        <span className="block text-xs text-muted-foreground">
                          {formatDate(ev.fecha)}
                        </span>
                      )}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
