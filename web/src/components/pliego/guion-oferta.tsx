"use client";

import * as React from "react";
import { Download, FileDown, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { PanelEmpty, PanelError, SUPERFICIE_PANEL } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PaginaPliegoDialog } from "@/components/pliego/pagina-pliego-dialog";
import { guionAMarkdown, useGuionOferta } from "@/hooks/use-guion-oferta";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import { ApiError, fetchBlobWithAuth } from "@/lib/api-client";
import { descargarBlob } from "@/lib/export";
import { getErrorMessage } from "@/lib/query-feedback";
import { cn } from "@/lib/utils";
import type { EvidenceRef } from "@/lib/api-types";

/**
 * F2.6 — guion de la oferta técnica por criterio (D33).
 *
 * Sólo esquema: puntos a cubrir por criterio, cada uno con sus citas al
 * pliego. Un punto sin cita se enseña **marcado** como «sin base en el
 * pliego», no se esconde: puede ser una buena idea, pero quien redacta tiene
 * que ver que es una propuesta y no una exigencia.
 *
 * Generarlo cuesta presupuesto de LLM de la organización, así que sólo se
 * pide con el botón. Cada cita abre la página del pliego (F2.5).
 */
export function GuionOfertaPanel({ licitacionId }: { licitacionId: string }) {
  const { guion, generar } = useGuionOferta(licitacionId);
  const documentos = useFactSheetDocumentos(licitacionId);
  const [cita, setCita] = React.useState<EvidenceRef | null>(null);
  const tituloId = React.useId();

  const nombreDoc = React.useCallback(
    (documentoId: number) => {
      const doc = documentos.data?.items.find((d) => d.id === documentoId);
      return doc ? (doc.filename ?? doc.tipo) : `Documento ${documentoId}`;
    },
    [documentos.data],
  );

  const descargar = () => {
    if (!guion) return;
    const blob = new Blob([guionAMarkdown(guion, nombreDoc)], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = `guion-oferta-${licitacionId.replace(/[^\w-]+/g, "_")}.md`;
    enlace.click();
    URL.revokeObjectURL(url);
  };

  // El PDF lo compone la API a partir del guion **ya generado** (no vuelve
  // a llamar al LLM). Un 404 significa que el guion guardado no corresponde al
  // pliego vigente —cambió, o la caché caducó—: se dice así, no como un error
  // de exportación genérico.
  const [descargandoPdf, setDescargandoPdf] = React.useState(false);
  const descargarPdf = async () => {
    setDescargandoPdf(true);
    try {
      const blob = await fetchBlobWithAuth(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/guion.pdf`,
      );
      descargarBlob(`guion-oferta-${licitacionId.replace(/[^\w-]+/g, "_")}.pdf`, blob, "guion");
    } catch (e) {
      toast.error("No se pudo descargar el PDF", {
        description:
          e instanceof ApiError && e.status === 404
            ? "El guion guardado ya no corresponde al pliego vigente. Vuelve a generarlo y descárgalo."
            : getErrorMessage(e, "accion"),
      });
    } finally {
      setDescargandoPdf(false);
    }
  };

  const error = generar.error;
  // El 429 trae en su `detail` cuándo vuelve a haber presupuesto: es lo que
  // hay que leer. El resto, con el mensaje humano de siempre.
  const mensajeError =
    error instanceof ApiError && error.status === 429
      ? `Presupuesto de IA agotado: ${error.message}`
      : error
        ? getErrorMessage(error, "accion")
        : null;
  const criterios = guion?.criterios ?? [];

  return (
    <section aria-labelledby={tituloId} className={cn(SUPERFICIE_PANEL, "mt-5 p-4")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={tituloId} className="text-tf-body font-semibold">
            Guion de la oferta técnica
          </h3>
          <p className="mt-1 max-w-prose text-tf-meta text-muted-foreground">
            Esquema de puntos a cubrir por cada criterio de adjudicación, con citas al pliego. No
            redacta la oferta: la prosa la escribe el equipo.
          </p>
        </div>
        <div className="flex gap-2">
          {guion && criterios.length > 0 && (
            <>
              <Button size="sm" variant="outline" onClick={descargar}>
                <Download aria-hidden="true" />
                Descargar Markdown
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void descargarPdf()}
                disabled={descargandoPdf}
              >
                {descargandoPdf ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <FileDown aria-hidden="true" />
                )}
                Descargar PDF
              </Button>
            </>
          )}
          <Button size="sm" onClick={() => generar.mutate()} disabled={generar.isPending}>
            {generar.isPending ? (
              <Loader2 className="animate-spin" aria-hidden="true" />
            ) : guion ? (
              <RefreshCw aria-hidden="true" />
            ) : null}
            {generar.isPending ? "Generando…" : guion ? "Regenerar" : "Generar guion"}
          </Button>
        </div>
      </div>

      {mensajeError && (
        <PanelError variant="inline" title="No se pudo generar el guion" message={mensajeError} error={error} />
      )}

      {guion?.sin_guion && <PanelEmpty size="sm" title="Sin guion para este pliego" hint={guion.sin_guion} />}

      {criterios.length > 0 && (
        <ol className="mt-4 space-y-4" aria-live="polite">
          {criterios.map((criterio, i) => (
            <li key={`${criterio.criterio}-${i}`}>
              <h4 className="text-tf-body font-semibold">
                {criterio.criterio}
                {criterio.peso_pct != null && (
                  <span className="font-normal text-muted-foreground"> · {criterio.peso_pct} puntos</span>
                )}
              </h4>
              <ul className="mt-1.5 space-y-2 border-l border-border/60 pl-3">
                {(criterio.puntos ?? []).map((punto, j) => (
                  <li key={j} className="text-tf-body">
                    <p>
                      {punto.texto}{" "}
                      {punto.sin_base && (
                        <Badge variant="warning" size="sm">
                          Sin base en el pliego
                        </Badge>
                      )}
                    </p>
                    {(punto.evidencia ?? []).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-tf-meta">
                        {(punto.evidencia ?? []).map((evidencia, k) => (
                          <button
                            key={k}
                            type="button"
                            onClick={() => setCita(evidencia)}
                            className="font-medium text-primary hover:underline"
                          >
                            {nombreDoc(evidencia.documento_id)} · p. {evidencia.page_number}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}

      {cita && (
        <PaginaPliegoDialog
          licitacionId={licitacionId}
          cita={cita}
          nombreDocumento={nombreDoc(cita.documento_id)}
          onClose={() => setCita(null)}
        />
      )}
    </section>
  );
}
