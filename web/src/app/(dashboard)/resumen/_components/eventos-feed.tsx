"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
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
import { fetchWithAuth } from "@/lib/api-client";
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

/** Feed de movimientos de contrato (prórrogas, modificaciones, anulaciones…)
 * — GET /api/v1/eventos, hoy sin explotar en ninguna otra página. */
export function EventosFeed() {
  const { data, isLoading } = useQuery<EventosFeedResult>({
    queryKey: ["eventos", "feed"],
    queryFn: () => fetchWithAuth<EventosFeedResult>("/api/v1/eventos?dias=30&limit=20"),
    staleTime: 2 * 60 * 1000,
  });

  const items = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4" />
          Movimientos del pipeline
        </CardTitle>
        <CardDescription>
          Últimos 30 días — prórrogas, modificaciones y adjudicaciones (dataset
          completo).
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
