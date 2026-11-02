"use client";

/**
 * «¿Cumples lo que piden?» en la ficha del expediente, antes de abrir la
 * oportunidad.
 *
 * Es el checklist de la oportunidad (`ChecklistGoNoGo`) contra
 * `GET /licitaciones/{id}/checklist`: los mismos veredictos por familia, con
 * la misma cita del pliego, sin tener que crear una oportunidad para leerlos.
 * Los conteos vienen de la respuesta; aquí no se suma nada (ADR-014).
 *
 * Arriba va la respuesta en una frase y, si algo queda sin contrastar por
 * falta de tu dato, qué familias son y dónde completarlo: casi toda
 * organización nueva llega sin capacidad declarada, y ocho «desconocido»
 * abiertos uno debajo de otro decían una sola cosa ocho veces. Por eso las
 * familias van plegadas, salvo las que no cumples, que son las que hay que leer.
 *
 * Cuando algo **no se cumple**, debajo van los socios con los que ir en UTE
 * en el segmento (`SociosUte`): un «no» con quién convertirlo en un «sí».
 */

import * as React from "react";
import { EnlaceIr, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { SociosUte } from "@/components/competitors/socios-ute";
import { ChecklistFamilia, faltaDatoPropio } from "@/components/pursuits/checklist-familia";
import { useChecklistLicitacion } from "@/hooks/use-licitacion";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

const COMPLETAR_CAPACIDAD = "/equipo?tab=organizacion";

/** «a», «a y b», «a, b y c». */
function enumerar(partes: string[]): string {
  if (partes.length <= 1) return partes.join("");
  return `${partes.slice(0, -1).join(", ")} y ${partes[partes.length - 1]}`;
}

function Cifra({ children }: { children: React.ReactNode }) {
  return <span className="tf-tnum text-foreground font-medium">{children}</span>;
}

export function FichaCumplo({ licitacion: l }: { licitacion: LicitacionDetail }) {
  const id = React.useId();
  const { data, isPending, error, refetch } = useChecklistLicitacion(l.id_externo);
  // Los mismos documentos que carga el bloque de pliegos: comparten caché.
  const documentos = useFactSheetDocumentos(l.id_externo);
  const docsById = new Map<number, DocumentoSummary>((documentos.data?.items ?? []).map((doc) => [doc.id, doc]));

  const titulo = (
    <PanelTitle
      as="h3"
      id={id}
      title="¿Cumples lo que piden?"
      hint="Lo que pide el expediente contra la capacidad de tu organización"
    />
  );

  if (isPending) {
    return (
      <section aria-labelledby={id}>
        {titulo}
        <PanelLoading height={96} />
      </section>
    );
  }
  if (error || !data) {
    return (
      <section aria-labelledby={id}>
        {titulo}
        <PanelError
          variant="inline"
          title="No se pudo contrastar el expediente con tu capacidad"
          error={error}
          onRetry={() => void refetch()}
        />
      </section>
    );
  }

  const conHechos = (data.familias ?? []).filter((familia) => !familia.sin_hechos);
  const hayFuente = data.ficha_estado != null || data.usa_condiciones_oficiales === true;
  const sinTuDato = conHechos
    .filter((familia) => (familia.items ?? []).some(faltaDatoPropio))
    .map((familia) => familia.etiqueta.toLowerCase());
  const total = data.requisitos_extraidos;
  const sinContrastar = data.desconocido_extraidos;

  return (
    <section aria-labelledby={id}>
      {titulo}
      {!hayFuente || total === 0 ? (
        <PanelEmpty
          size="sm"
          title="Todavía no hay requisitos con los que comparar"
          hint="Aparecen cuando se extrae la ficha del pliego o el anuncio publica la solvencia. Abrir la oportunidad lanza la extracción."
        />
      ) : (
        <>
          <div className="mb-3">
            <p role="status" className="text-tf-body leading-relaxed text-pretty">
              {data.cumple + data.no_cumple === 0 ? (
                <>
                  Todavía no se puede contrastar ninguno de los <Cifra>{total}</Cifra>{" "}
                  {total === 1 ? "requisito" : "requisitos"}.
                </>
              ) : (
                <>
                  De <Cifra>{total}</Cifra> {total === 1 ? "requisito" : "requisitos"}, cumples{" "}
                  <Cifra>{data.cumple}</Cifra> y no cumples <Cifra>{data.no_cumple}</Cifra>
                  {sinContrastar > 0 ? (
                    <>
                      ; <Cifra>{sinContrastar}</Cifra> {sinContrastar === 1 ? "queda" : "quedan"} sin contrastar
                    </>
                  ) : null}
                  .
                </>
              )}
            </p>
            {sinContrastar > 0 ? (
              <div className="text-muted-foreground text-tf-meta mt-1 leading-relaxed text-pretty">
                <p>
                  Sin contrastar es una pregunta abierta, no un no.
                  {sinTuDato.length > 0 ? ` Falta tu dato en ${enumerar(sinTuDato)}.` : null}
                </p>
                {sinTuDato.length > 0 ? (
                  <EnlaceIr href={COMPLETAR_CAPACIDAD} className="mt-1.5">
                    Completar la capacidad de tu organización (Equipo › Organización)
                  </EnlaceIr>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="space-y-2">
            {conHechos.map((familia) => (
              <ChecklistFamilia
                key={familia.familia}
                familia={familia}
                docsById={docsById}
                abierta={familia.veredicto === "no_cumple"}
              />
            ))}
          </div>
        </>
      )}

      {data.no_cumple > 0 ? (
        <div className="border-divider mt-4 border-t pt-4">
          <p className="text-muted-foreground text-tf-meta mb-2 leading-relaxed">
            No cumples {data.no_cumple === 1 ? "un requisito" : `${data.no_cumple} requisitos`}. Estas empresas ganan en
            este segmento y suelen ir en UTE:
          </p>
          <SociosUte cpv={l.cpv} ccaa={l.ccaa} />
        </div>
      ) : null}
    </section>
  );
}
