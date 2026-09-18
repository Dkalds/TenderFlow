"use client";

/**
 * Pestaña «Favoritos»: licitaciones marcadas una a una, no capturadas por una
 * regla de criterio.
 *
 * Tiene sus propias queries (`useWatchlistItems`) en vez de recibirlas de la
 * página porque solo se monta cuando la pestaña está activa: quien nunca abre
 * Favoritos no paga la petición.
 */

import { Trash2, Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CompararBoton } from "@/components/pliego/comparacion-bandeja";
import { EtiquetaChips, EtiquetasEditor } from "@/components/etiquetas/etiquetas-objeto";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import {
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";
import { formatCurrency, formatDate, truncate } from "@/lib/utils";

export function FavoritosPanel() {
  const { data: items, isLoading } = useWatchlistItems();
  const removeItem = useRemoveWatchlistItem();
  // F1.6 — el favorito se etiqueta por su `id_externo`; una sola petición
  // para toda la lista.
  const etiquetas =
    useEtiquetasDe("favorito", (items ?? []).map((item) => item.id_externo)).data ?? {};

  if (isLoading) {
    return (
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
    );
  }

  if (!items || items.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <Star className="h-12 w-12 text-muted-foreground/50 mb-4" />
          <p className="text-lg font-medium text-muted-foreground">
            No tienes licitaciones marcadas como favoritas
          </p>
          <p className="text-sm text-muted-foreground/70 mt-1">
            Marca licitaciones con la estrella desde la tabla de Detalle.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <Card key={item.id_externo} className="hover:bg-accent/30 transition-colors">
          <CardContent className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
            <div className="flex-1 min-w-0">
              <a
                href={`/detalle?lic=${item.id_externo}`}
                className="text-sm font-medium hover:underline line-clamp-1"
              >
                {truncate(item.titulo ?? item.id_externo, 100)}
              </a>
              <EtiquetaChips etiquetas={etiquetas[item.id_externo]} className="mt-1" />
            </div>
            <EtiquetasEditor
              objetoTipo="favorito"
              objetoId={item.id_externo}
              aplicadas={etiquetas[item.id_externo]}
              descripcion={truncate(item.titulo ?? item.id_externo, 60)}
            />
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
            <CompararBoton
              id={item.id_externo}
              titulo={item.titulo}
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border border-border/80 px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground aria-pressed:border-primary/50 aria-pressed:text-primary"
            />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0 text-destructive"
                  aria-label="Quitar de favoritos"
                  onClick={() => removeItem.mutate(item.id_externo)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Quitar de favoritos</TooltipContent>
            </Tooltip>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
