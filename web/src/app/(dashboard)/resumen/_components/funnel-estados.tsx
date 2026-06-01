"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatNumber } from "@/lib/utils";
import { getSeriesColor } from "@/lib/chart-colors";

interface FunnelEstadosProps {
  funnelEstados: { estado: string; n: number }[];
}

export function FunnelEstados({ funnelEstados }: FunnelEstadosProps) {
  if (funnelEstados.length === 0) return null;

  const maxN = Math.max(...funnelEstados.map((f) => f.n));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Funnel de Estados</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {funnelEstados.map((item, idx) => {
            const pct = maxN > 0 ? (item.n / maxN) * 100 : 0;
            return (
              <div key={idx} className="flex items-center gap-3">
                <span className="w-32 text-sm text-muted-foreground truncate">{item.estado}</span>
                <div className="flex-1 h-6 bg-muted rounded-sm overflow-hidden">
                  <div
                    className="h-full rounded-sm transition-all"
                    style={{
                      width: `${pct}%`,
                      backgroundColor: getSeriesColor(idx),
                    }}
                  />
                </div>
                <Badge variant="secondary" className="tabular-nums">
                  {formatNumber(item.n)}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
