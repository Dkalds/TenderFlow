"use client";

import * as React from "react";
import { ExternalLink, Loader2 } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { toast } from "sonner";
import { PaginaPliegoDialog } from "@/components/pliego/pagina-pliego-dialog";
import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
// Del módulo de los pulgares, no de `chat-thread`: importarlos de allí metía
// el hilo de chat entero (react-markdown incluido) en la pestaña Pliego.
import { FeedbackButtons } from "@/components/feedback-buttons";
import {
  type AnyFact,
  type EvidenceRef,
  type FactSheetStatus,
  type TenderFactSheet,
  useFactSheetDocumentos,
  useTenderFactSheet,
  useTenderFactSheetExtraction,
} from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import { getErrorMessage } from "@/lib/query-feedback";
import { formatCurrency, formatDate } from "@/lib/utils";

const categories: Array<{ key: keyof TenderFactSheet; label: string }> = [
  { key: "lots", label: "Lotes" },
  { key: "award_criteria", label: "Criterios de adjudicación" },
  { key: "technical_solvency", label: "Solvencia técnica" },
  { key: "economic_solvency", label: "Solvencia económica" },
  { key: "guarantees", label: "Garantías" },
  { key: "penalties", label: "Penalizaciones" },
  { key: "service_levels", label: "Niveles de servicio (ANS/SLA)" },
  { key: "subcontracting", label: "Subcontratación" },
  { key: "team_requirements", label: "Equipo requerido" },
  { key: "certifications", label: "Certificaciones" },
  { key: "extensions", label: "Prórrogas" },
  { key: "critical_deadlines", label: "Fechas críticas" },
];

const SCOPE_LABELS: Record<string, string> = { company: "Empresa", team: "Equipo" };

function statusPresentation(status: FactSheetStatus) {
  if (status === "extracted") return { label: "Verificada", variant: "success" as const };
  if (status === "needs_review") return { label: "Revisar", variant: "warning" as const };
  if (status === "failed") return { label: "No disponible", variant: "destructive" as const };
  return { label: "Pendiente", variant: "neutral" as const };
}

/**
 * La confianza que autoinforma el LLM no está calibrada: un "86%" pintado como
 * porcentaje exacto aparenta una precisión que no tiene. Se presenta como
 * ordinal (alta/media/baja) con el número crudo como detalle secundario.
 */
function confidencePresentation(confidence: number): { label: string; pct: number } {
  const pct = Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  if (pct >= 75) return { label: "Confianza alta", pct };
  if (pct >= 45) return { label: "Confianza media", pct };
  return { label: "Confianza baja", pct };
}

/**
 * Lee un campo que solo existe en algunas familias de hechos.
 *
 * La API tipa cada familia por separado (`WeightedCriterion` tiene
 * `weight_pct`, `MonetaryFact` tiene `amount_eur`…). Esta fila las renderiza
 * todas, así que consulta los campos opcionales con una comprobación explícita
 * en vez de asumir un tipo aplanado que la API nunca prometió.
 */
function optionalField<T>(item: AnyFact, key: string): T | null {
  return key in item ? ((item as unknown as Record<string, T | null>)[key] ?? null) : null;
}

/** Etiqueta y enlace de una cita, resueltos contra los metadatos del documento.
 *
 *  Sin el índice (aún cargando, o fila purgada) se degrada al id interno, que
 *  al menos es estable. El enlace añade `#page=N`: los visores de PDF del
 *  navegador lo respetan y abren el documento por la página citada. */
function citaPresentation(
  documentoId: number,
  pageNumber: number,
  docsById: Map<number, DocumentoSummary>,
): { label: string; href: string | null } {
  const doc = docsById.get(documentoId);
  if (!doc) return { label: `Documento ${documentoId} · página ${pageNumber}`, href: null };
  const nombre = doc.filename ?? doc.tipo;
  return {
    label: `${nombre} · página ${pageNumber}`,
    href: doc.uri ? `${doc.uri}#page=${pageNumber}` : null,
  };
}

function FactRow({
  item,
  docsById,
  onVerPagina,
}: {
  item: AnyFact;
  docsById: Map<number, DocumentoSummary>;
  onVerPagina: (cita: EvidenceRef) => void;
}) {
  const confidence = confidencePresentation(item.confidence);
  const name = optionalField<string>(item, "name");
  const role = optionalField<string>(item, "role");
  const weightPct = optionalField<number>(item, "weight_pct");
  const amountEur = optionalField<number>(item, "amount_eur");
  const quantity = optionalField<number>(item, "quantity");
  const minimumYears = optionalField<number>(item, "minimum_years");
  const dateValue = optionalField<string>(item, "date_value");
  const lotNumber = optionalField<string>(item, "lot_number");
  const target = optionalField<string>(item, "target");
  const scope = optionalField<string>(item, "scope");
  const evidence = item.evidence ?? [];

  const title =
    name || role || (lotNumber ? `Lote ${lotNumber}` : null) || item.description || "Campo extraído";
  const metadata = [
    lotNumber && title !== `Lote ${lotNumber}` ? `Lote ${lotNumber}` : null,
    weightPct != null ? `Peso ${weightPct}%` : null,
    amountEur != null ? formatCurrency(amountEur) : null,
    target ? `Objetivo ${target}` : null,
    scope ? (SCOPE_LABELS[scope] ?? null) : null,
    quantity != null ? `${quantity} persona(s)` : null,
    minimumYears != null ? `${minimumYears} años mínimos` : null,
    dateValue ? formatDate(dateValue) : null,
  ].filter(Boolean);
  return (
    <li className="rounded-md border border-border/70 bg-background p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 text-tf-body font-medium leading-snug">{title}</p>
        <span className="tf-tnum shrink-0 text-tf-meta font-medium text-muted-foreground">
          {confidence.label} · {confidence.pct}%
        </span>
      </div>
      {item.description && item.description !== title && (
        <p className="mt-1 text-tf-body text-muted-foreground">{item.description}</p>
      )}
      {metadata.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {metadata.map((value) => (
            <Badge key={value} size="sm">
              {value}
            </Badge>
          ))}
        </div>
      )}
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
        aria-label={`${confidence.label} (${confidence.pct}%)`}
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${confidence.pct}%` }} />
      </div>
      {evidence.length > 0 && (
        <details className="mt-3 text-tf-meta">
          <summary className="cursor-pointer font-medium text-primary hover:underline">
            {evidence.length} cita{evidence.length === 1 ? "" : "s"} verificable
            {evidence.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-2 border-l border-border/60 pl-3">
            {evidence.map((cita, index) => {
              const fuente = citaPresentation(cita.documento_id, cita.page_number, docsById);
              return (
                <li key={`${cita.documento_id}-${cita.page_number}-${index}`}>
                  {fuente.href ? (
                    <a
                      href={fuente.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                    >
                      {fuente.label}
                      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
                      <AvisoPestanaNueva />
                    </a>
                  ) : (
                    <p className="font-medium text-muted-foreground">{fuente.label}</p>
                  )}
                  <blockquote className="mt-1 leading-relaxed text-foreground/85">
                    «{cita.quote}»
                  </blockquote>
                  {/* F2.5 — la página del pliego con la cita resaltada, sin
                      salir de la ficha: el enlace de arriba lleva al portal,
                      que no siempre responde y nunca marca el fragmento. */}
                  <button
                    type="button"
                    onClick={() => onVerPagina(cita)}
                    className="mt-1 inline-flex items-center gap-1 font-medium text-primary hover:underline"
                  >
                    Ver la cita en su página
                  </button>
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </li>
  );
}

export function TenderFactSheetPanel({ licitacionId }: { licitacionId: string }) {
  const factSheet = useTenderFactSheet(licitacionId);
  const extraction = useTenderFactSheetExtraction(licitacionId);
  const documentos = useFactSheetDocumentos(licitacionId);
  const record = factSheet.data;
  const presentation = record ? statusPresentation(record.status) : null;
  const isMissing =
    factSheet.error instanceof Error &&
    "status" in factSheet.error &&
    (factSheet.error as { status?: number }).status === 404;
  const docsById = new Map<number, DocumentoSummary>(
    (documentos.data?.items ?? []).map((doc) => [doc.id, doc]),
  );
  const extracting = extraction.isStarting || extraction.running;
  const [citaAbierta, setCitaAbierta] = React.useState<EvidenceRef | null>(null);
  const docCita = citaAbierta ? docsById.get(citaAbierta.documento_id) : undefined;

  const requestExtraction = async () => {
    try {
      await extraction.start();
      toast.info("Extracción lanzada: la ficha aparecerá aquí en unos minutos");
    } catch (error) {
      toast.error("No se pudo lanzar la extracción de la ficha", {
        description: getErrorMessage(error, "accion"),
      });
    }
  };

  const extractButton = (label: string) => (
    <Button size="sm" onClick={() => void requestExtraction()} disabled={extracting}>
      {extracting ? (
        <>
          <Loader2 className="animate-spin" aria-hidden="true" />
          Extrayendo…
        </>
      ) : (
        label
      )}
    </Button>
  );

  return (
    <Panel>
      <PanelTitle
        title="Ficha estructurada del pliego"
        hint="Requisitos que se pueden comprobar en una página concreta del documento."
        actions={presentation ? <Badge variant={presentation.variant}>{presentation.label}</Badge> : undefined}
      />
      <div>
        {factSheet.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : factSheet.error && !isMissing ? (
          <PanelError
            variant="inline"
            title="No se pudo recuperar la ficha del pliego"
            error={factSheet.error}
            onRetry={() => void factSheet.refetch()}
          />
        ) : !record || record.status === "pending" || record.status === "failed" || !record.facts ? (
          <div>
            <PanelEmpty
              title={extracting ? "Extrayendo la ficha del pliego…" : "Aún no hay una ficha verificable"}
              hint={
                extracting
                  ? "Se están descargando los pliegos pendientes y extrayendo los requisitos. Puedes seguir navegando: la ficha aparecerá aquí sola."
                  : "La ficha se extrae sola al abrir una oportunidad y en las pasadas nocturnas, que priorizan los expedientes con oportunidad o favorito. Puedes lanzarla ahora. Solo se muestra lo que pueda citarse desde el pliego: los campos sin evidencia quedan vacíos."
              }
              action={extractButton(record ? "Reprocesar ficha" : "Extraer ficha")}
            />
            {!extracting && record?.error_detail && (
              // El motivo del último fallo es técnico: plegado, para soporte.
              <details className="mx-auto max-w-[420px] text-center text-tf-meta text-muted-foreground">
                <summary className="cursor-pointer text-destructive">El último intento falló</summary>
                <p className="mt-1 break-all font-mono text-tf-micro">{record.error_detail}</p>
              </details>
            )}
          </div>
        ) : (
          <div className="space-y-5">
            {/* Un anuncio TED que reenvía un expediente de PLACSP no trae pliegos:
                la API devuelve la ficha del expediente original, y se dice. */}
            {record.licitacion_id !== licitacionId && (
              <Aviso tone="info" role="note">
                Pliegos del expediente original {record.licitacion_id}: esta licitación es su republicación y no publica
                documentos propios.
              </Aviso>
            )}
            {record.status === "needs_review" && (
              <Aviso tone="warning" role="note">
                Se han descartado campos sin una cita verificable, o que el pliego devolvió en un
                formato que no encaja. Cada cita visible sigue vinculada a su documento y página.
              </Aviso>
            )}
            <div className="tf-tnum flex flex-wrap gap-x-5 gap-y-1 text-tf-meta text-muted-foreground">
              <span>{record.field_count} campos con evidencia</span>
              <span>{record.evidence_count} citas verificables</span>
              <span>Versión {record.extraction_version}</span>
            </div>
            {categories.map((category) => {
              const items = record.facts?.[category.key] ?? [];
              return items.length ? (
                <section key={category.key}>
                  <SectionTitle className="mb-2" hint={items.length}>
                    {category.label}
                  </SectionTitle>
                  <ul className="space-y-2">
                    {items.map((item, index) => (
                      <FactRow
                        key={`${category.key}-${index}`}
                        item={item}
                        docsById={docsById}
                        onVerPagina={setCitaAbierta}
                      />
                    ))}
                  </ul>
                </section>
              ) : null;
            })}
            <div className="flex items-center justify-between border-t border-border/60 pt-4">
              <FeedbackButtons modo="ficha" />
              <Button
                variant="outline"
                size="sm"
                onClick={() => void requestExtraction()}
                disabled={extracting}
              >
                {extracting && <Loader2 className="animate-spin" aria-hidden="true" />}
                {extracting ? "Extrayendo…" : "Reprocesar"}
              </Button>
            </div>
          </div>
        )}
      </div>
      {/* Montado sólo con una cita abierta: cerrado no pide nada. */}
      {citaAbierta && (
        <PaginaPliegoDialog
          licitacionId={licitacionId}
          cita={citaAbierta}
          nombreDocumento={docCita ? (docCita.filename ?? docCita.tipo) : null}
          onClose={() => setCitaAbierta(null)}
        />
      )}
    </Panel>
  );
}
