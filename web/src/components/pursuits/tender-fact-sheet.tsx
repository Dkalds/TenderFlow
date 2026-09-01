"use client";

import { AlertCircle, BookOpenCheck, ExternalLink, FileText, Loader2, RefreshCw, ScanText } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { FeedbackButtons } from "@/components/chat-thread";
import {
  type AnyFact,
  type FactSheetStatus,
  type TenderFactSheet,
  useFactSheetDocumentos,
  useTenderFactSheet,
  useTenderFactSheetExtraction,
} from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
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
  return { label: "Pendiente", variant: "secondary" as const };
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
 * El backend tipa cada familia por separado (`WeightedCriterion` tiene
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

function FactRow({ item, docsById }: { item: AnyFact; docsById: Map<number, DocumentoSummary> }) {
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
    <li className="rounded-lg border border-border/70 bg-background/45 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 font-medium leading-snug">{title}</p>
        <span className="shrink-0 text-xs font-semibold text-muted-foreground">
          {confidence.label} · {confidence.pct}%
        </span>
      </div>
      {item.description && item.description !== title && (
        <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
      )}
      {metadata.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {metadata.map((value) => (
            <Badge key={value} variant="secondary">
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
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer font-medium text-primary hover:underline">
            {evidence.length} cita{evidence.length === 1 ? "" : "s"} verificable
            {evidence.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-2 border-l-2 border-primary/25 pl-3">
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
                    </a>
                  ) : (
                    <p className="font-medium text-muted-foreground">{fuente.label}</p>
                  )}
                  <blockquote className="mt-1 leading-relaxed text-foreground/85">
                    «{cita.quote}»
                  </blockquote>
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

  const requestExtraction = async () => {
    try {
      await extraction.start();
      toast.info("Extracción lanzada: la ficha aparecerá aquí en unos minutos");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "No se pudo lanzar la extracción de la ficha",
      );
    }
  };

  const extractButton = (label: string) => (
    <Button onClick={() => void requestExtraction()} disabled={extracting}>
      {extracting ? (
        <>
          <Loader2 className="animate-spin" />
          Extrayendo…
        </>
      ) : (
        <>
          <FileText />
          {label}
        </>
      )}
    </Button>
  );

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <BookOpenCheck className="h-4 w-4 text-primary" />
            Ficha estructurada del pliego
          </CardTitle>
          <CardDescription className="mt-1">
            Requisitos que se pueden comprobar en una página concreta del documento.
          </CardDescription>
        </div>
        {presentation && <Badge variant={presentation.variant}>{presentation.label}</Badge>}
      </CardHeader>
      <CardContent>
        {factSheet.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : factSheet.error && !isMissing ? (
          <div
            role="alert"
            className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
          >
            <p className="font-semibold">No se pudo recuperar la ficha del pliego.</p>
            <p className="mt-1">{(factSheet.error as Error).message}</p>
            <Button className="mt-3" size="sm" variant="outline" onClick={() => void factSheet.refetch()}>
              <RefreshCw />
              Reintentar
            </Button>
          </div>
        ) : !record || record.status === "pending" || record.status === "failed" || !record.facts ? (
          <div className="rounded-lg border border-dashed bg-muted/25 p-5 text-center">
            <ScanText className="mx-auto h-8 w-8 text-muted-foreground" />
            <h3 className="mt-3 font-semibold">
              {extracting ? "Extrayendo la ficha del pliego…" : "Aún no hay una ficha verificable"}
            </h3>
            <p className="mx-auto mt-1 max-w-lg text-sm text-muted-foreground">
              {extracting
                ? "Se están descargando los pliegos pendientes y extrayendo los requisitos. Puedes seguir navegando: la ficha aparecerá aquí sola."
                : "La extracción solo muestra información que pueda citarse desde el pliego. Los campos sin evidencia se mantienen vacíos."}
            </p>
            {!extracting && record?.error_detail && (
              <p className="mt-2 text-xs text-destructive">Último intento: {record.error_detail}</p>
            )}
            <div className="mt-4">{extractButton(record ? "Reprocesar ficha" : "Extraer ficha")}</div>
          </div>
        ) : (
          <div className="space-y-5">
            {record.status === "needs_review" && (
              <div className="flex gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>
                  Se han descartado campos sin una cita verificable, o que el pliego devolvió en un
                  formato que no encaja. Cada cita visible sigue vinculada a su documento y página.
                </p>
              </div>
            )}
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
              <span>{record.field_count} campos con evidencia</span>
              <span>{record.evidence_count} citas verificables</span>
              <span>Versión {record.extraction_version}</span>
            </div>
            {categories.map((category) => {
              const items = record.facts?.[category.key] ?? [];
              return items.length ? (
                <section key={category.key}>
                  <h3 className="mb-2 text-sm font-semibold">
                    {category.label}{" "}
                    <span className="font-normal text-muted-foreground">· {items.length}</span>
                  </h3>
                  <ul className="space-y-2">
                    {items.map((item, index) => (
                      <FactRow key={`${category.key}-${index}`} item={item} docsById={docsById} />
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
                {extracting ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                {extracting ? "Extrayendo…" : "Reprocesar"}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
