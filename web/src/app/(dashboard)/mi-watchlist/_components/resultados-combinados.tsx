"use client";

/**
 * Coincidencias reales de todas las reglas activas, ya deduplicadas.
 *
 * Es la sección que responde «¿y esto qué me trae?»: sin ella la pantalla solo
 * enseña criterios y un contador, y no hay forma de saber si una regla está
 * capturando lo que su autor cree. El deduplicado lo hace `dedupeMatches` —dos
 * reglas del mismo usuario suelen solapar—, aquí solo se pinta.
 *
 * Una lista en un solo panel, una fila por licitación: el título enlaza a su
 * ficha en Detalle.
 */

import Link from "next/link";
import { PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDate, formatNumber, truncate } from "@/lib/utils";
import type { MatchItem } from "../_hooks/watchlist-rule-types";

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
        <PanelTitle
          as="h2"
          title="Resultados combinados"
          hint={combined ? `${formatNumber(combined.length)} licitaciones` : undefined}
        />

        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full rounded-md" />
            ))}
          </div>
        ) : combined && combined.length > 0 ? (
          <ul className="divide-y divide-border/50 rounded-xl border border-border/60 bg-card">
            {combined.map((item, i) => {
              const id = item.id_externo ?? String(i);
              return (
                <li key={id} className="flex flex-col gap-2 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4">
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/detalle?lic=${encodeURIComponent(item.id_externo ?? "")}`}
                      className="line-clamp-1 text-tf-body font-medium hover:underline"
                    >
                      {truncate(item.titulo ?? "Sin título", 100)}
                    </Link>
                    {item.organo_contratacion && (
                      <p className="truncate text-tf-meta text-muted-foreground">{item.organo_contratacion}</p>
                    )}
                  </div>
                  {item.importe != null && (
                    <span className="tf-tnum shrink-0 text-tf-meta font-medium">{formatCurrency(item.importe)}</span>
                  )}
                  {item.estado && (
                    <Badge size="sm" variant="outline" className="shrink-0">
                      {item.estado}
                    </Badge>
                  )}
                  {item.fecha_publicacion && (
                    <span className="tf-tnum shrink-0 text-tf-meta text-muted-foreground">
                      {formatDate(item.fecha_publicacion)}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          // Qué hacer con un vacío (C7.3): cada criterio de una regla
          // restringe, así que la salida es aflojar alguno.
          <PanelEmpty
            title="Ninguna licitación coincide con tus reglas activas"
            hint="Cada criterio de una regla se suma a los demás: edita la regla y quita o afloja alguno (el importe mínimo o la CCAA suelen ser los que más recortan)."
          />
        )}
      </div>
    </>
  );
}
