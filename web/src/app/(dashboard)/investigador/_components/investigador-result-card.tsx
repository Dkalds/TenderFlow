"use client";

/**
 * Una licitación dentro de la lista de resultados: título enlazado a su ficha,
 * relevancia, extracto con la consulta resaltada e importe.
 */

import Link from "next/link";
import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatPercent, truncate } from "@/lib/utils";
import { highlightQuery } from "../_lib/highlight";
import type { SearchResult } from "../_lib/types";

/**
 * Relevancia en tres tramos. El score es el del backend; los cortes (0.8/0.5)
 * son de presentación y solo agrupan lo que ya se pinta en porcentaje al lado.
 * Tonos de la casa (antes verde y amarillo crudos, con texto blanco sobre el
 * amarillo a ~2:1).
 */
function relevanceBadge(score: number | undefined) {
  if (score == null) return null;
  if (score >= 0.8) return <Badge variant="success">Alta</Badge>;
  if (score >= 0.5) return <Badge variant="warning">Media</Badge>;
  return <Badge variant="neutral">Baja</Badge>;
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
  const id = result.id_externo ?? result.id ?? result.expediente ?? "";

  return (
    <Panel>
      <div className="flex items-start justify-between gap-4">
        <h3 className="min-w-0 text-tf-body font-semibold">
          <Link href={`/detalle?lic=${encodeURIComponent(String(id))}`} className="hover:underline">
            {result.titulo ?? "Sin título"}
          </Link>
        </h3>
        <div className="flex shrink-0 items-center gap-1.5">
          {relevanceBadge(result.score)}
          {result.score != null && (
            <Badge variant="outline" className="tf-tnum">
              {formatPercent(result.score * 100)}
            </Badge>
          )}
        </div>
      </div>
      {organo && <p className="mt-0.5 text-tf-meta text-muted-foreground">{organo}</p>}
      {excerpt && <p className="mt-2 text-tf-body text-muted-foreground">{highlightQuery(excerpt, query)}</p>}
      {result.importe != null && (
        <p className="tf-tnum mt-2 text-tf-meta font-medium">{formatCurrency(result.importe)}</p>
      )}
    </Panel>
  );
}
