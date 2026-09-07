"use client";

/**
 * Los dos estados transitorios de la búsqueda: el esqueleto mientras carga y la
 * tarjeta de error cuando el backend devuelve un `detail` RFC-7807.
 */

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function InvestigadorSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <Card key={i}>
          <CardContent className="space-y-2 pt-6">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function InvestigadorError({ message }: { message: string }) {
  return (
    <Card className="border-destructive">
      <CardContent className="pt-6">
        <p className="text-destructive font-medium">Error: {message}</p>
      </CardContent>
    </Card>
  );
}
