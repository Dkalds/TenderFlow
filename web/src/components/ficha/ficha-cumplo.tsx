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
 * Cuando algo **no se cumple**, debajo van los socios con los que ir en UTE
 * en el segmento (`SociosUte`): un «no» con quién convertirlo en un «sí».
 */

import Link from "next/link";
import { PanelEmpty, PanelError, PanelLoading, SectionTitle } from "@/components/console/panel";
import { SociosUte } from "@/components/competitors/socios-ute";
import { ChecklistFamilia } from "@/components/pursuits/checklist-familia";
import { useChecklistLicitacion } from "@/hooks/use-licitacion";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

export function FichaCumplo({ licitacion: l, as = "h3" }: { licitacion: LicitacionDetail; as?: "h3" | "h4" }) {
  const { data, isPending, error, refetch } = useChecklistLicitacion(l.id_externo);
  // Los mismos documentos que carga el bloque de pliegos: comparten caché.
  const documentos = useFactSheetDocumentos(l.id_externo);
  const docsById = new Map<number, DocumentoSummary>((documentos.data?.items ?? []).map((doc) => [doc.id, doc]));

  const titulo = (
    <SectionTitle as={as} hint="Lo que pide el expediente contra la capacidad de tu organización">
      ¿Cumples lo que piden?
    </SectionTitle>
  );

  if (isPending) {
    return (
      <section aria-label="¿Cumples lo que piden?">
        {titulo}
        <PanelLoading height={96} />
      </section>
    );
  }
  if (error || !data) {
    return (
      <section aria-label="¿Cumples lo que piden?">
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

  return (
    <section aria-label="¿Cumples lo que piden?">
      {titulo}
      {!hayFuente || data.requisitos_extraidos === 0 ? (
        <PanelEmpty
          size="sm"
          title="Todavía no hay requisitos con los que comparar"
          hint="Aparecen cuando se extrae la ficha del pliego o el anuncio publica la solvencia. Abrir la oportunidad lanza la extracción."
        />
      ) : (
        <>
          <p role="status" className="text-muted-foreground text-tf-meta mb-2.5 leading-relaxed">
            De {data.requisitos_extraidos} {data.requisitos_extraidos === 1 ? "requisito" : "requisitos"}:{" "}
            <span className="tf-tnum text-foreground font-medium">{data.cumple}</span> «cumple» ·{" "}
            <span className="tf-tnum text-foreground font-medium">{data.no_cumple}</span> «no cumple» ·{" "}
            <span className="tf-tnum text-foreground font-medium">{data.desconocido_extraidos}</span> «desconocido».
          </p>
          <div className="space-y-2">
            {conHechos.map((familia) => (
              <ChecklistFamilia key={familia.familia} familia={familia} docsById={docsById} />
            ))}
          </div>
          {data.desconocido_extraidos > 0 ? (
            <p className="text-muted-foreground text-tf-micro mt-2.5 leading-relaxed">
              Un «desconocido» es una pregunta abierta, no un no. Si falta tu dato, complétalo en{" "}
              <Link href="/equipo?tab=organizacion" className="text-primary font-medium hover:underline">
                la capacidad de tu organización
              </Link>
              .
            </p>
          ) : null}
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
