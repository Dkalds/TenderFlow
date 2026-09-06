"use client";

/** Rejilla de componentes del health: uno por cada `check` que trae la API. */

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { detalleComponente, estadoComponente } from "./health-checks";

export interface ComponentesGridProps {
  /** Componentes tal como llegan del health; vacío = no se pinta la sección. */
  checks: Record<string, unknown>;
}

export function ComponentesGrid({ checks }: ComponentesGridProps) {
  const entradas = Object.entries(checks);
  if (entradas.length === 0) return null;

  return (
    <>
      <h2 className="text-xl font-semibold">Componentes</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {entradas.map(([key, value]) => {
          const estado = estadoComponente(value);
          return (
            <Card key={key}>
              <CardContent className="pt-5">
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-medium capitalize">{key}</span>
                  <Badge
                    variant={estado === "ok" ? "default" : "destructive"}
                    className={cn(
                      estado === "ok" &&
                        "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
                    )}
                  >
                    {estado === "ok" ? "OK" : "Error"}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {detalleComponente(key, value)}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <Separator />
    </>
  );
}
