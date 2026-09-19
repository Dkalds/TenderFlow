"use client";

import * as React from "react";
import { Download, ListChecks, Loader2, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PaginaPliegoDialog } from "@/components/pliego/pagina-pliego-dialog";
import { guionAMarkdown, useGuionOferta } from "@/hooks/use-guion-oferta";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import { ApiError } from "@/lib/api-client";
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

  const error = generar.error;
  const mensajeError =
    error instanceof ApiError && error.status === 429
      ? `Presupuesto de IA agotado: ${error.message}`
      : error
        ? `No se pudo generar el guion. ${(error as Error).message}`
        : null;
  const criterios = guion?.criterios ?? [];

  return (
    <section aria-labelledby={tituloId} className="mt-5 rounded-xl border border-border/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={tituloId} className="flex items-center gap-2 text-sm font-semibold">
            <ListChecks className="h-4 w-4 text-primary" aria-hidden="true" />
            Guion de la oferta técnica
          </h3>
          <p className="mt-1 max-w-prose text-xs text-muted-foreground">
            Esquema de puntos a cubrir por cada criterio de adjudicación, con citas al pliego. No
            redacta la oferta: la prosa la escribe el equipo.
          </p>
        </div>
        <div className="flex gap-2">
          {guion && criterios.length > 0 && (
            <Button size="sm" variant="outline" onClick={descargar}>
              <Download aria-hidden="true" />
              Descargar Markdown
            </Button>
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
        <p role="alert" className="mt-3 text-sm text-destructive">
          {mensajeError}
        </p>
      )}

      {guion?.sin_guion && (
        <p className="mt-3 rounded-lg border border-dashed border-border/70 bg-muted/25 p-3 text-sm text-muted-foreground">
          {guion.sin_guion}
        </p>
      )}

      {criterios.length > 0 && (
        <ol className="mt-4 space-y-4" aria-live="polite">
          {criterios.map((criterio, i) => (
            <li key={`${criterio.criterio}-${i}`}>
              <h4 className="text-sm font-semibold">
                {criterio.criterio}
                {criterio.peso_pct != null && (
                  <span className="font-normal text-muted-foreground"> · {criterio.peso_pct} puntos</span>
                )}
              </h4>
              <ul className="mt-1.5 space-y-2 border-l-2 border-primary/25 pl-3">
                {(criterio.puntos ?? []).map((punto, j) => (
                  <li key={j} className="text-sm">
                    <p className="leading-snug">
                      {punto.texto}{" "}
                      {punto.sin_base && <Badge variant="warning">Sin base en el pliego</Badge>}
                    </p>
                    {(punto.evidencia ?? []).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
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
