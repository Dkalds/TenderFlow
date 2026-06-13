"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { formatCurrency, truncate } from "@/lib/utils";
import type { TopLicitacionesResult } from "@/generated/api";

interface TopLicitacionesListProps {
  data: TopLicitacionesResult | undefined;
  isLoading: boolean;
}

export function TopLicitacionesList({ data, isLoading }: TopLicitacionesListProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top 10 Licitaciones</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : data?.items && data.items.length > 0 ? (
          <div className="divide-y">
            {data.items.map((item) => (
              <div
                key={item.id_externo}
                className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-sm truncate">{truncate(item.titulo, 80)}</p>
                  <p className="text-xs text-muted-foreground truncate">{item.organo_contratacion}</p>
                  {item.adjudicatario && (
                    <p className="text-xs text-muted-foreground">Adj: {item.adjudicatario}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="font-semibold text-sm tabular-nums">
                    {formatCurrency(item.importe)}
                  </span>
                  <Badge variant="secondary">{item.estado}</Badge>
                  {item.baja_pct != null && (
                    <Badge variant="outline" className="text-xs">
                      -{item.baja_pct.toFixed(1)}%
                    </Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
