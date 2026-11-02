"use client";

/**
 * «Tu historial aquí»: lo que tu organización ha ganado con el órgano y en el
 * CPV del expediente, y cómo acabaron sus oportunidades con ese órgano
 * (`GET /licitaciones/{id}/historial-propio`). Todo viene calculado; aquí no
 * se suma nada (ADR-014).
 *
 * Los dos ámbitos son independientes y sin ventana de tiempo: «con este
 * órgano» cuenta cualquier CPV y «en el CPV» cualquier órgano
 * (`db/repositories/competencia_esperada.py::historial_propio`). Se dice en el
 * rótulo porque justo encima Competencia esperada habla de tu cuota en órgano
 * y CPV a la vez y en 36 meses, y sin decirlo las dos cifras no cuadran.
 */

import * as React from "react";
import Link from "next/link";
import { EnlaceFicha } from "@/components/ficha/enlace-ficha";
import { Fact, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { useHistorialPropio } from "@/hooks/use-licitacion";
import type { HistorialPropio } from "@/lib/api-types";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

type Resumen = NonNullable<HistorialPropio["con_organo"]>;

function contar(n: number, singular: string, plural: string): string {
  return `${formatNumber(n)} ${n === 1 ? singular : plural}`;
}

function ValorResumen({ resumen }: { resumen: Resumen }) {
  if (resumen.expedientes === 0) return <>Ninguna adjudicación</>;
  return (
    <>
      <span className="tf-tnum">{contar(resumen.expedientes, "ganada", "ganadas")}</span>
      <span className="text-muted-foreground text-tf-meta block font-normal">
        {formatCurrency(resumen.importe)} adjudicados
        {resumen.baja_mediana_pct != null
          ? ` · baja mediana ${formatPercent(resumen.baja_mediana_pct)} en ${contar(resumen.bajas_n, "adjudicación", "adjudicaciones")}`
          : null}
      </span>
    </>
  );
}

function ambitoDe(adj: NonNullable<HistorialPropio["recientes"]>[number]): string {
  if (adj.mismo_organo && adj.mismo_cpv4) return "mismo órgano y CPV";
  return adj.mismo_organo ? "mismo órgano" : "mismo CPV";
}

export function FichaHistorialPropio({ licitacionId }: { licitacionId: string }) {
  const id = React.useId();
  const { data, isPending, error, refetch } = useHistorialPropio(licitacionId);
  const titulo = <PanelTitle as="h3" id={id} title="Tu historial aquí" hint="Sin ventana de tiempo, por tu NIF" />;

  if (isPending || error || !data) {
    return (
      <section aria-labelledby={id}>
        {titulo}
        {isPending ? (
          <PanelLoading height={96} />
        ) : (
          <PanelError
            variant="inline"
            title="No se pudo cargar tu historial"
            error={error}
            onRetry={() => void refetch()}
          />
        )}
      </section>
    );
  }

  if (!data.identidad_conocida) {
    return (
      <section aria-labelledby={id}>
        {titulo}
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
      </section>
    );
  }

  const oportunidades = data.oportunidades && data.oportunidades.total > 0 ? data.oportunidades : null;
  const celdas: { clave: string; label: string; value: React.ReactNode }[] = [];
  if (data.con_organo) {
    celdas.push({
      clave: "organo",
      label: "Con este órgano · cualquier CPV",
      value: <ValorResumen resumen={data.con_organo} />,
    });
  }
  if (data.en_cpv4) {
    celdas.push({
      clave: "cpv",
      label: `En el CPV ${data.cpv4} · cualquier órgano`,
      value: <ValorResumen resumen={data.en_cpv4} />,
    });
  }
  if (oportunidades) {
    celdas.push({
      clave: "oportunidades",
      label: "Tus oportunidades con el órgano",
      value: (
        <>
          <span className="tf-tnum">{contar(oportunidades.total, "oportunidad", "oportunidades")}</span>
          <span className="text-muted-foreground text-tf-meta block font-normal">
            {contar(oportunidades.presentadas, "presentada", "presentadas")} ·{" "}
            {contar(oportunidades.ganadas, "ganada", "ganadas")} ·{" "}
            {contar(oportunidades.perdidas, "perdida", "perdidas")}
          </span>
        </>
      ),
    });
  }
  const recientes = data.recientes ?? [];

  if (celdas.length === 0 && recientes.length === 0) {
    return (
      <section aria-labelledby={id}>
        {titulo}
        <PanelEmpty size="sm" title="Todavía no has ganado nada con este órgano ni en este CPV" />
      </section>
    );
  }

  return (
    <section aria-labelledby={id}>
      {titulo}
      {celdas.length > 0 ? (
        // Una columna: el panel vive en la columna estrecha de la ficha, y a dos
        // el detalle de cada cifra se partía en cuatro líneas.
        <div className="border-divider bg-divider grid gap-px overflow-hidden rounded-md border">
          {celdas.map((celda) => (
            <Fact key={celda.clave} label={celda.label} value={celda.value} />
          ))}
        </div>
      ) : null}
      {recientes.length > 0 ? (
        <>
          <h4 className="text-muted-foreground text-tf-meta mt-4 mb-1 font-semibold">Lo último que has ganado</h4>
          <ul className="divide-divider divide-y">
            {recientes.map((adj) => (
              <li key={adj.licitacion_id} className="py-2">
                <EnlaceFicha
                  idExterno={adj.licitacion_id}
                  className="text-tf-body hover:text-primary font-medium text-pretty"
                >
                  {adj.titulo || adj.licitacion_id}
                </EnlaceFicha>
                <p className="text-muted-foreground text-tf-meta text-pretty">
                  {[
                    ambitoDe(adj),
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
        </>
      ) : (
        <p className="text-muted-foreground text-tf-meta mt-2">
          Todavía no has ganado nada con este órgano ni en este CPV.
        </p>
      )}
    </section>
  );
}
