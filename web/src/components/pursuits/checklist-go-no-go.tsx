"use client";

/**
 * Contraste de la ficha del pliego con la capacidad declarada (S2.3).
 *
 * **Es la primera vista de la oportunidad (D54, plan 2026-10).** Va arriba de
 * la pestaña Resumen, antes de la salida de fase y de la decisión; la matriz
 * ponderada quedó plegada al final. Por eso el panel es una región con nombre
 * propio, «Checklist go/no-go», y su pie remite a la decisión «más abajo».
 *
 * El motor (`services/go_no_go.py`) y su endpoint existían desde el PR #274 y
 * ninguna pantalla los montaba: la pestaña Decisión pedía decidir sin enseñar
 * contra qué se decide. Esto lo enseña, y **sólo** lo enseña:
 *
 * - No decide. El go/no-go se sigue marcando a mano en el formulario de
 *   decisión que hay justo encima, y el panel lo dice en su pie.
 * - `desconocido` se muestra como tal, con el motivo que da la API, y
 *   cuando lo que falta es el dato de la organización enlaza a donde se
 *   rellena (`/equipo?tab=organizacion`, que abre esa pestaña).
 * - Declara sobre qué ficha se evaluó: `extraction_version` y su fecha. Un
 *   veredicto sin decir de qué versión del pliego sale no es verificable.
 *
 * Los conteos (`cumple`, `no_cumple`, `requisitos_extraidos`,
 * `desconocido_extraidos`) vienen de la respuesta; aquí no se suma nada
 * (ADR-014).
 *
 * **Una familia sin hechos no es un requisito.** La API manda para cada
 * familia de la que la ficha no sacó nada un ítem que lo avisa; pintado como
 * requisito, un pliego sin requisitos extraídos salía como «De 4 requisitos
 * extraídos» y cuatro tarjetas iguales con el mismo enlace al perfil de
 * capacidad, que no arregla nada: lo que falta ahí es el pliego, no el perfil.
 * Esas familias van en una línea (`sin_hechos`).
 *
 * **La publicación oficial también cuenta (v148).** Cuando PLACSP publica la
 * solvencia en el propio anuncio, el backend contrasta esa y no la de la
 * ficha (`usa_condiciones_oficiales`). Entonces hay veredictos aunque no haya
 * ficha extraída, y la procedencia declara también la fecha de la publicación
 * evaluada.
 */

import { Panel, PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
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

/** Nombre del panel y de su región: lo que D54 llama el checklist. */
const TITULO = "Checklist go/no-go";

/** Qué ficha se evaluó. Sin esto el veredicto no se puede volver a comprobar. */
function Procedencia({
  extractionVersion,
  fichaActualizada,
  condicionesActualizadas,
}: {
  extractionVersion: string | null | undefined;
  fichaActualizada: string | null | undefined;
  condicionesActualizadas: string | null | undefined;
}) {
  const partes = [
    fichaActualizada ? `ficha del ${formatDate(fichaActualizada)}` : null,
    extractionVersion ? `extractor ${extractionVersion}` : null,
    condicionesActualizadas ? `publicación oficial del ${formatDate(condicionesActualizadas)}` : null,
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
      <Panel id={ANCLA} role="region" aria-label={TITULO}>
        <SectionTitle>{TITULO}</SectionTitle>
        <Skeleton className="h-[132px] w-full rounded-md" />
      </Panel>
    );
  }

  if (error || !data) {
    return (
      <Panel id={ANCLA} role="region" aria-label={TITULO}>
        <SectionTitle>{TITULO}</SectionTitle>
        <PanelError
          variant="inline"
          title="No se pudo contrastar el pliego con tu capacidad"
          error={error}
          message={error ? undefined : "No hay respuesta que enseñar. Vuelve a intentarlo."}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  const familias = data.familias ?? [];
  const oficial = data.usa_condiciones_oficiales === true;
  // Hay algo contrastado si hay ficha o si el backend usó la publicación oficial.
  const hayFuente = data.ficha_estado != null || oficial;
  const n = data.requisitos_extraidos;
  const recuento = !oficial
    ? `${n === 1 ? "requisito extraído" : "requisitos extraídos"} del pliego`
    : `${n === 1 ? "requisito contrastado" : "requisitos contrastados"} con ${
        data.ficha_estado == null ? "" : "el pliego y "
      }la publicación oficial de PLACSP`;
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
    <Panel id={ANCLA} role="region" aria-label={TITULO} tabIndex={-1} className="outline-none">
      <SectionTitle
        hint={
          <Procedencia
            extractionVersion={data.extraction_version}
            fichaActualizada={data.ficha_actualizada}
            condicionesActualizadas={data.condiciones_actualizadas}
          />
        }
      >
        {TITULO}
      </SectionTitle>

      {!hayFuente ? (
        <PanelEmpty
          title="Todavía no hay ficha del pliego extraída"
          hint="Sin ficha no hay nada contra lo que contrastar tu capacidad. La extracción se lanza desde la pestaña «Pliego»."
          action={
            onAbrirPliego ? (
              <Button type="button" variant="outline" size="sm" onClick={onAbrirPliego}>
                Abrir la pestaña «Pliego»
              </Button>
            ) : undefined
          }
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
            De {n} {recuento}:{" "}
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
      {hayFuente && data.requisitos_extraidos > 0 ? (
        <p className="text-muted-foreground mt-3 text-tf-micro leading-relaxed">
          Esto no decide el Go/No-Go: lo propone. La decisión se marca a mano en «Decisión del
          comité», más abajo, y un «desconocido» es una pregunta abierta, no un no.
        </p>
      ) : null}
    </Panel>
  );
}
