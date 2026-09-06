"use client";

/**
 * Una licitación dentro de la lista de resultados: título enlazado a su ficha,
 * relevancia, extracto con la consulta resaltada e importe.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency, truncate } from "@/lib/utils";
import { highlightQuery } from "../_lib/highlight";
import type { SearchResult } from "../_lib/types";

/**
 * Relevancia en tres tramos. El score es el del backend; los cortes (0.8/0.5)
 * son de presentación y solo agrupan lo que ya se pinta en porcentaje al lado.
 */
function relevanceBadge(score: number | undefined) {
  if (score == null) return null;
  if (score >= 0.8) return <Badge className="bg-green-600 text-white hover:bg-green-700">Alta</Badge>;
  if (score >= 0.5) return <Badge className="bg-yellow-500 text-white hover:bg-yellow-600">Media</Badge>;
  return <Badge variant="secondary">Baja</Badge>;
}

interface Props {
  result: SearchResult;
  /** La consulta que produjo el hit: se resalta dentro del extracto. */
  query: string;
}

export function InvestigadorResultCard({ result, query }: Props) {
  const organo = result.organo_contratacion ?? result.organo ?? "";
  const texto = result.descripcion ?? result.description;
  const excerpt = texto ? truncate(texto, 200) : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-4">
          <CardTitle className="text-base leading-snug">
            <a
              href={`/detalle?lic=${result.id_externo ?? result.id ?? result.expediente ?? ""}`}
              className="hover:underline"
            >
              {result.titulo ?? "Sin título"}
            </a>
          </CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            {relevanceBadge(result.score)}
            {result.score != null && <Badge variant="outline">{(result.score * 100).toFixed(1)}%</Badge>}
          </div>
        </div>
        {organo && <CardDescription>{organo}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-2">
        {/* Context excerpt */}
        {excerpt && <p className="text-muted-foreground text-sm">{highlightQuery(excerpt, query)}</p>}
        <div className="flex items-center gap-4">
          {result.importe != null && <Badge variant="secondary">{formatCurrency(result.importe)}</Badge>}
        </div>
      </CardContent>
    </Card>
  );
}
