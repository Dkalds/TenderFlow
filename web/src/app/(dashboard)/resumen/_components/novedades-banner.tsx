"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Info } from "lucide-react";
import { formatCurrency, truncate } from "@/lib/utils";
import type { ResumenNovedadesResult } from "@/generated/api";

interface NovedadesBannerProps {
  data: ResumenNovedadesResult | undefined;
  isLoading: boolean;
}

export function NovedadesBanner({ data, isLoading }: NovedadesBannerProps) {
  if (isLoading) {
    return <Skeleton className="h-20 w-full" />;
  }

  if (!data) return null;

  if (data.count > 0) {
    return (
      <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
        <CardContent className="py-4">
          <div className="flex items-start gap-3">
            <Info className="mt-0.5 h-5 w-5 text-blue-600 dark:text-blue-400 shrink-0" />
            <div className="space-y-2">
              <p className="font-medium text-blue-900 dark:text-blue-100">
                {data.count} nuevas licitaciones desde tu ultima visita
              </p>
              <ul className="space-y-1 text-sm text-blue-800 dark:text-blue-200">
                {data.sample.slice(0, 5).map((item) => (
                  <li key={item.id_externo} className="flex items-center justify-between gap-4">
                    <span className="truncate">{truncate(item.titulo, 60)}</span>
                    {item.importe != null && (
                      <span className="shrink-0 font-medium">{formatCurrency(item.importe)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950">
      <CardContent className="flex items-center justify-center py-4">
        <p className="text-green-800 dark:text-green-200 text-sm font-medium">Todo al dia</p>
      </CardContent>
    </Card>
  );
}
