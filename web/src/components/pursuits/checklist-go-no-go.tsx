"use client";

/**
 * Contraste de la ficha del pliego con la capacidad declarada (S2.3).
 *
 * El motor (`services/go_no_go.py`) y su endpoint existían desde el PR #274 y
 * ninguna pantalla los montaba: la pestaña Decisión pedía decidir sin enseñar
 * contra qué se decide. Esto lo enseña, y **sólo** lo enseña:
 *
 * - No decide. El go/no-go se sigue marcando a mano en el formulario de
 *   decisión que hay justo encima, y el panel lo dice en su pie.
 * - `desconocido` se muestra como tal, con el motivo que da el backend, y
 *   cuando lo que falta es el dato de la organización enlaza a donde se
 *   rellena (`/equipo`, pestaña Organización).
 * - Declara sobre qué ficha se evaluó: `extraction_version` y su fecha. Un
 *   veredicto sin decir de qué versión del pliego sale no es verificable.
 *
 * Los conteos (`cumple`, `no_cumple`, `desconocido`, `total_requisitos`) vienen
 * de la respuesta; aquí no se suma nada (ADR-014).
 */

import { Panel, PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { usePursuitChecklist } from "@/hooks/use-pursuit-checklist";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import { formatDate } from "@/lib/utils";
import { ChecklistFamilia } from "./checklist-familia";

/** Qué ficha se evaluó. Sin esto el veredicto no se puede volver a comprobar. */
function Procedencia({
  extractionVersion,
  fichaActualizada,
}: {
  extractionVersion: string | null | undefined;
  fichaActualizada: string | null | undefined;
}) {
  const partes = [
    fichaActualizada ? `ficha del ${formatDate(fichaActualizada)}` : null,
    extractionVersion ? `extractor ${extractionVersion}` : null,
  ].filter(Boolean);
  if (partes.length === 0) return <>sin versión de ficha declarada</>;
  return <>{partes.join(" · ")}</>;
}

export function ChecklistGoNoGo({
  pursuitId,
  licitacionId,
}: {
  pursuitId: number | string;
  licitacionId: string;
}) {
  const { data, isLoading, error, refetch } = usePursuitChecklist(pursuitId);
  // Los mismos documentos que ya carga la pestaña Pliego: comparten clave de
  // caché, así que abrir las dos no son dos peticiones.
  const documentos = useFactSheetDocumentos(licitacionId);
  const docsById = new Map<number, DocumentoSummary>(
    (documentos.data?.items ?? []).map((doc) => [doc.id, doc]),
  );

  if (isLoading) {
    return (
      <Panel className="mt-3.5">
        <SectionTitle>Requisitos del pliego</SectionTitle>
        <Skeleton className="h-[132px] w-full rounded-lg" />
      </Panel>
    );
  }

  if (error || !data) {
    return (
      <Panel className="mt-3.5">
        <SectionTitle>Requisitos del pliego</SectionTitle>
        <PanelError
          title="No se pudo contrastar el pliego con tu capacidad"
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  const familias = data.familias ?? [];

  return (
    <Panel className="mt-3.5">
      <SectionTitle
        aside={
          <Procedencia
            extractionVersion={data.extraction_version}
            fichaActualizada={data.ficha_actualizada}
          />
        }
      >
        Requisitos del pliego
      </SectionTitle>

      {data.ficha_estado == null ? (
        <PanelEmpty message="Todavía no hay ficha del pliego extraída, así que no hay nada contra lo que contrastar tu capacidad. La extracción se lanza desde la pestaña «Pliego»." />
      ) : (
        <>
          <p className="mb-2.5 text-[11.5px] leading-relaxed text-muted-foreground">
            De {data.total_requisitos} requisito{data.total_requisitos === 1 ? "" : "s"} extraído
            {data.total_requisitos === 1 ? "" : "s"} del pliego:{" "}
            <span className="tf-tnum font-medium text-foreground">{data.cumple}</span> «cumple» ·{" "}
            <span className="tf-tnum font-medium text-foreground">{data.no_cumple}</span> «no
            cumple» ·{" "}
            <span className="tf-tnum font-medium text-foreground">{data.desconocido}</span>{" "}
            «desconocido».
          </p>

          <div className="space-y-2">
            {familias.map((familia) => (
              <ChecklistFamilia key={familia.familia} familia={familia} docsById={docsById} />
            ))}
          </div>
        </>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
        Esto no decide el go/no-go: lo propone. La decisión se marca a mano en el selector
        «Decisión» de arriba, y un «desconocido» es una pregunta abierta, no un no.
      </p>
    </Panel>
  );
}
