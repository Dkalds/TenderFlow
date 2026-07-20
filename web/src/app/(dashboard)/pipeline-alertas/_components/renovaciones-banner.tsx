"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ArrowRight, RefreshCw } from "lucide-react";
import { fetchWithAuth } from "@/lib/api-client";
import { formatCurrency, formatNumber } from "@/lib/utils";

interface RenovacionesResumenTotales {
  contratos_venciendo: number;
  importe_en_juego: number;
}

interface RenovacionesResumenResponse {
  totales?: RenovacionesResumenTotales;
}

const MONTHS_AHEAD = 6;

/** Banner compacto hacia /renovaciones — sustituye al bloque "Forecast
 * re-licitación" que duplicaba esa página. Totales server-side (ADR-014):
 * GET /api/v1/competitive/renovaciones/resumen, sin derivar nada en cliente. */
export function RenovacionesBanner() {
  const { data, isLoading } = useQuery<RenovacionesResumenResponse>({
    queryKey: ["competitive", "renovaciones", "resumen", "totales", MONTHS_AHEAD],
    queryFn: () =>
      fetchWithAuth<RenovacionesResumenResponse>(
        `/api/v1/competitive/renovaciones/resumen?months=${MONTHS_AHEAD}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) return <Skeleton className="h-20 w-full" />;

  const totales = data?.totales;
  if (!totales || totales.contratos_venciendo === 0) return null;

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div className="flex items-center gap-2 text-sm">
          <RefreshCw className="h-4 w-4 shrink-0 text-primary" />
          <span>
            <strong className="font-semibold">
              {formatNumber(totales.contratos_venciendo)}
            </strong>{" "}
            contratos vencen en los próximos {MONTHS_AHEAD} meses ·{" "}
            <strong className="font-semibold">
              {formatCurrency(totales.importe_en_juego)}
            </strong>{" "}
            en juego
          </span>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/renovaciones">
            Ver renovaciones
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
