"use client";

/**
 * Completitud por columna.
 *
 * El gráfico entra por `next/dynamic` sin SSR: recharts no se renderiza en
 * servidor y arrastra su propio bundle, que no tiene por qué viajar con el
 * resto de la pantalla.
 */

import dynamic from "next/dynamic";
import { ShieldCheck } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ColumnCompleteness } from "./quality-data";

const CalidadCompletenessChart = dynamic(
  () =>
    import("@/components/charts/calidad-datos-charts").then((m) => ({
      default: m.CalidadCompletenessChart,
    })),
  { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> },
);

export interface CompletitudCardProps {
  data: ColumnCompleteness[];
  isLoading: boolean;
}

export function CompletitudCard({ data, isLoading }: CompletitudCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5" />
          Completitud por columna
        </CardTitle>
        <CardDescription>Porcentaje de registros con campos completos</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : (
          <CalidadCompletenessChart data={data} />
        )}
      </CardContent>
    </Card>
  );
}
