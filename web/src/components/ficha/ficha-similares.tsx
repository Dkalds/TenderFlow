"use client";

import * as React from "react";
import Link from "next/link";
import { PanelEmpty, PanelError, PanelLoading, SectionTitle } from "@/components/console/panel";
import { useSimilares } from "@/hooks/use-licitacion";
import { estadoLabel } from "@/lib/estados";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

/** Cómo se ordenaron, en palabras de quien lee (`metodo` de la respuesta). */
const ORDEN: Record<string, string> = {
  fts: "palabras en común",
  embedding: "parecido de significado",
};

/**
 * Expedientes parecidos a este, de cualquier órgano y del mismo CPV
 * (`GET /licitaciones/{id}/similares`, que existía sin consumidor).
 *
 * El predecesor que trae la misma respuesta no se repite aquí: lo enseña la
 * competencia esperada como incumbente. El pie dice cuántos candidatos se
 * evaluaron y por qué criterio se ordenaron (ADR-014): sin embeddings el orden
 * es peor, y una lista ordenada por un criterio que no se dice no se puede leer.
 */
export function FichaSimilares({ licitacionId, as = "h3" }: { licitacionId: string; as?: "h3" | "h4" }) {
  const id = React.useId();
  const { data, isPending, error, refetch } = useSimilares(licitacionId);
  // `default_factory=list` en el DTO: el esquema la marca opcional, llega siempre.
  const similares = data?.similares ?? [];

  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id}>
        Expedientes parecidos
      </SectionTitle>
      {isPending ? (
        <PanelLoading height={96} />
      ) : error || !data ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los parecidos"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : similares.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún expediente parecido"
          hint={
            data.n === 0
              ? "No hay otros expedientes del mismo CPV con los que comparar."
              : `Ninguno de los ${formatNumber(data.n)} expedientes evaluados aparece como parecido.`
          }
        />
      ) : (
        <>
          <ul className="divide-border/60 divide-y">
            {similares.map((similar) => (
              <li key={similar.id_externo} className="py-2 first:pt-0">
                <Link
                  href={`/detalle?lic=${encodeURIComponent(similar.id_externo)}`}
                  className="text-tf-body font-medium text-pretty hover:text-primary"
                >
                  {similar.titulo || similar.id_externo}
                </Link>
                <p className="text-muted-foreground text-tf-meta">
                  {[
                    similar.organo_contratacion,
                    similar.importe != null ? formatCurrency(similar.importe) : null,
                    similar.estado ? estadoLabel(similar.estado) : null,
                    similar.fecha_publicacion ? `publicado el ${formatDate(similar.fecha_publicacion)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground mt-2 text-tf-micro">
            {formatNumber(data.n)} expedientes del mismo CPV evaluados, ordenados por{" "}
            {ORDEN[data.metodo ?? "fts"] ?? data.metodo}.
          </p>
        </>
      )}
    </section>
  );
}
