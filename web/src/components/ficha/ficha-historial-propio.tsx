"use client";

/**
 * «Tu historial aquí»: lo que tu organización ha ganado con el órgano y en el
 * CPV del expediente, y cómo acabaron sus oportunidades con ese órgano
 * (`GET /licitaciones/{id}/historial-propio`). Todo viene calculado; aquí no
 * se suma nada (ADR-014).
 */

import * as React from "react";
import Link from "next/link";
import { Fact, PanelEmpty, PanelError, PanelLoading, SectionTitle } from "@/components/console/panel";
import { useHistorialPropio } from "@/hooks/use-licitacion";
import type { HistorialPropio } from "@/lib/api-types";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

type Resumen = NonNullable<HistorialPropio["con_organo"]>;

function textoResumen(resumen: Resumen): string {
  if (resumen.expedientes === 0) return "Ninguna adjudicación";
  const partes = [
    `${formatNumber(resumen.expedientes)} ${resumen.expedientes === 1 ? "ganada" : "ganadas"}`,
    formatCurrency(resumen.importe),
  ];
  if (resumen.baja_mediana_pct != null) {
    partes.push(`baja mediana ${formatPercent(resumen.baja_mediana_pct)} (n=${resumen.bajas_n})`);
  }
  return partes.join(" · ");
}

export function FichaHistorialPropio({ licitacionId, as = "h3" }: { licitacionId: string; as?: "h3" | "h4" }) {
  const id = React.useId();
  const { data, isPending, error, refetch } = useHistorialPropio(licitacionId);

  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id} hint="Lo que tu organización ha ganado con este órgano y en este CPV">
        Tu historial aquí
      </SectionTitle>
      {isPending ? (
        <PanelLoading height={96} />
      ) : error || !data ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar tu historial"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : !data.identidad_conocida ? (
        <PanelEmpty
          size="sm"
          title="Declara el NIF de tu organización"
          hint="Sin él no se puede reconocer lo que has ganado."
          action={
            <Link href="/equipo?tab=organizacion" className="text-primary text-tf-meta font-medium hover:underline">
              Ir a la capacidad de tu organización
            </Link>
          }
        />
      ) : (
        <>
          <div className="border-divider bg-divider grid gap-px overflow-hidden rounded-md border sm:grid-cols-2">
            {data.con_organo ? <Fact label="Con este órgano" value={textoResumen(data.con_organo)} /> : null}
            {data.en_cpv4 ? <Fact label={`En el CPV ${data.cpv4}`} value={textoResumen(data.en_cpv4)} /> : null}
            {data.oportunidades && data.oportunidades.total > 0 ? (
              <Fact
                label="Tus oportunidades con el órgano"
                value={`${formatNumber(data.oportunidades.total)} en total · ${formatNumber(
                  data.oportunidades.presentadas,
                )} presentadas · ${formatNumber(data.oportunidades.ganadas)} ganadas · ${formatNumber(
                  data.oportunidades.perdidas,
                )} perdidas`}
              />
            ) : null}
          </div>
          {(data.recientes ?? []).length > 0 ? (
            <ul className="divide-divider mt-3 divide-y">
              {(data.recientes ?? []).map((adj) => (
                <li key={adj.licitacion_id} className="py-2 first:pt-0">
                  <Link
                    href={`/detalle?lic=${encodeURIComponent(adj.licitacion_id)}`}
                    className="text-tf-body hover:text-primary font-medium text-pretty"
                  >
                    {adj.titulo || adj.licitacion_id}
                  </Link>
                  <p className="text-muted-foreground text-tf-meta">
                    {[
                      adj.mismo_organo ? "mismo órgano" : "mismo CPV",
                      adj.importe_adjudicado != null ? formatCurrency(adj.importe_adjudicado) : null,
                      adj.baja_pct != null ? `baja ${formatPercent(adj.baja_pct)}` : null,
                      adj.fecha_adjudicacion ? `adjudicada el ${formatDate(adj.fecha_adjudicacion)}` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground text-tf-meta mt-2">
              Todavía no has ganado nada con este órgano ni en este CPV.
            </p>
          )}
        </>
      )}
    </section>
  );
}
