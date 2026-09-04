"use client";

/**
 * Coincidencias reales de todas las reglas activas, ya deduplicadas.
 *
 * Es la sección que responde «¿y esto qué me trae?»: sin ella la pantalla solo
 * enseña criterios y un contador, y no hay forma de saber si una regla está
 * capturando lo que su autor cree. El deduplicado lo hace `dedupeMatches` —dos
 * reglas del mismo usuario suelen solapar—, aquí solo se pinta.
 */

import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDate, truncate } from "@/lib/utils";
import type { MatchItem } from "../_hooks/use-watchlist-rules";

export function ResultadosCombinados({
  combined,
  loading,
}: {
  combined: MatchItem[] | undefined;
  loading: boolean;
}) {
  return (
    <>
      <Separator />
      <div>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Search className="h-5 w-5" />
          Resultados combinados
          {combined && <Badge variant="secondary">{combined.length}</Badge>}
        </h2>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="pt-6 space-y-2">
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : combined && combined.length > 0 ? (
          <div className="space-y-2">
            {combined.map((item, i) => {
              const id = item.id_externo ?? String(i);
              return (
                <Card key={id} className="hover:bg-accent/30 transition-colors">
                  <CardContent className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                    <div className="flex-1 min-w-0">
                      <a
                        href={`/detalle?lic=${item.id_externo ?? ""}`}
                        className="text-sm font-medium hover:underline line-clamp-1"
                      >
                        {truncate(item.titulo ?? "Sin título", 100)}
                      </a>
                      {item.organo_contratacion && (
                        <p className="text-xs text-muted-foreground truncate">
                          {item.organo_contratacion}
                        </p>
                      )}
                    </div>
                    {item.importe != null && (
                      <Badge variant="secondary" className="shrink-0">
                        {formatCurrency(item.importe)}
                      </Badge>
                    )}
                    {item.estado && (
                      <Badge variant="outline" className="shrink-0">
                        {item.estado}
                      </Badge>
                    )}
                    {item.fecha_publicacion && (
                      <span className="text-xs text-muted-foreground shrink-0">
                        {formatDate(item.fecha_publicacion)}
                      </span>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : (
          <Card className="border-dashed">
            <CardContent className="py-8 text-center text-muted-foreground">
              No se encontraron licitaciones que coincidan con tus reglas activas.
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
