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
 * Los conteos (`cumple`, `no_cumple`, `requisitos_extraidos`,
 * `desconocido_extraidos`) vienen de la respuesta; aquí no se suma nada
 * (ADR-014).
 *
 * **Una familia sin hechos no es un requisito.** El backend manda para cada
 * familia de la que la ficha no sacó nada un ítem que lo avisa; pintado como
 * requisito, un pliego sin requisitos extraídos salía como «De 4 requisitos
 * extraídos» y cuatro tarjetas iguales con el mismo enlace al perfil de
 * capacidad, que no arregla nada: lo que falta ahí es el pliego, no el perfil.
 * Esas familias van en una línea (`sin_hechos`).
 */

import { Panel, PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { usePursuitChecklist } from "@/hooks/use-pursuit-checklist";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import { formatDate } from "@/lib/utils";
import { ChecklistFamilia } from "./checklist-familia";

/** «A», «B» y «C» o, en negativa, «A», «B» ni «C». */
function enumerar(etiquetas: string[], ultimo: "y" | "ni"): string {
  const citadas = etiquetas.map((etiqueta) => `«${etiqueta}»`);
  if (citadas.length <= 1) return citadas.join("");
  return `${citadas.slice(0, -1).join(", ")} ${ultimo} ${citadas[citadas.length - 1]}`;
}

/** Ancla y foco de la ficha: el paso «Requisitos del pliego contrastados» lleva aquí. */
const ANCLA = "ficha-requisitos";

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
  onAbrirPliego,
}: {
  pursuitId: number | string;
  licitacionId: string;
  /** Lleva a la pestaña «Pliego», donde se extrae o se revisa la ficha. */
  onAbrirPliego?: () => void;
}) {
  const { data, isPending, error, refetch } = usePursuitChecklist(pursuitId);
  // Los mismos documentos que ya carga la pestaña Pliego: comparten clave de
  // caché, así que abrir las dos no son dos peticiones.
  const documentos = useFactSheetDocumentos(licitacionId);
  const docsById = new Map<number, DocumentoSummary>(
    (documentos.data?.items ?? []).map((doc) => [doc.id, doc]),
  );

  if (isPending) {
    return (
      <Panel id={ANCLA}>
        <SectionTitle>Requisitos del pliego</SectionTitle>
        <Skeleton className="h-[132px] w-full rounded-lg" />
      </Panel>
    );
  }

  if (error || !data) {
    return (
      <Panel id={ANCLA}>
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
  const conHechos = familias.filter((familia) => !familia.sin_hechos);
  const sinHechos = familias.filter((familia) => familia.sin_hechos).map((familia) => familia.etiqueta);
  const irAPliego = onAbrirPliego ? (
    <button
      type="button"
      onClick={onAbrirPliego}
      className="text-primary font-medium hover:underline"
    >
      Abrir la pestaña «Pliego»
    </button>
  ) : null;

  return (
    <Panel id={ANCLA} tabIndex={-1} className="outline-none">
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
        <PanelEmpty
          message="Todavía no hay ficha del pliego extraída, así que no hay nada contra lo que contrastar tu capacidad. La extracción se lanza desde la pestaña «Pliego»."
          action={irAPliego ?? undefined}
        />
      ) : data.requisitos_extraidos === 0 ? (
        <p role="status" className="text-muted-foreground text-tf-meta leading-relaxed">
          La ficha del pliego no extrajo ningún requisito de {enumerar(sinHechos, "ni")}, así que no
          hay nada que contrastar con tu capacidad: lo que falta es el pliego, no tu perfil.{" "}
          {irAPliego ?? "Revísalo en la pestaña «Pliego»."}
        </p>
      ) : (
        <>
          <p className="text-muted-foreground mb-2.5 text-tf-meta leading-relaxed">
            De {data.requisitos_extraidos} requisito{data.requisitos_extraidos === 1 ? "" : "s"} extraído
            {data.requisitos_extraidos === 1 ? "" : "s"} del pliego:{" "}
            <span className="tf-tnum text-foreground font-medium">{data.cumple}</span> «cumple» ·{" "}
            <span className="tf-tnum text-foreground font-medium">{data.no_cumple}</span> «no
            cumple» ·{" "}
            <span className="tf-tnum text-foreground font-medium">{data.desconocido_extraidos}</span>{" "}
            «desconocido».
          </p>

          <div className="space-y-2">
            {conHechos.map((familia) => (
              <ChecklistFamilia key={familia.familia} familia={familia} docsById={docsById} />
            ))}
          </div>

          {sinHechos.length > 0 ? (
            <p className="text-muted-foreground mt-2.5 text-tf-micro leading-relaxed">
              Sin requisitos extraídos del pliego: {enumerar(sinHechos, "y")}.
            </p>
          ) : null}
        </>
      )}

      {/* Solo cuando hay veredictos: sin nada contrastado, advertir de que un
          veredicto no decide es una frase más que leer sin nada debajo. */}
      {data.ficha_estado != null && data.requisitos_extraidos > 0 ? (
        <p className="text-muted-foreground mt-3 text-tf-micro leading-relaxed">
          Esto no decide el go/no-go: lo propone. La decisión se marca a mano en «Decisión del
          comité», arriba, y un «desconocido» es una pregunta abierta, no un no.
        </p>
      ) : null}
    </Panel>
  );
}
