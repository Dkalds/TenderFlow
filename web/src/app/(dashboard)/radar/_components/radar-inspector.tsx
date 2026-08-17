"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, ExternalLink, Loader2, Star, X } from "lucide-react";
import { fetchWithAuth } from "@/lib/api-client";
import { fuenteLinkLabel } from "@/lib/fuentes";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { RadarTender } from "@/hooks/use-radar";
import {
  DESGLOSE_LABELS,
  bandColor,
  bandColorAlpha,
  daysLeft,
  urgency,
} from "./radar-shared";

/**
 * Inspector del Radar — vive en el mismo plano que la lista, no encima.
 *
 * El detalle era un Sheet modal que tapaba la tabla: comparar dos señales
 * exigía abrir, leer, cerrar y volver a abrir. Aquí el panel **sigue a la
 * selección**, así que recorrer con J/K es leer el detalle de cada fila sin
 * ningún gesto extra. Por eso tampoco hace crossfade al cambiar de fila: con
 * J/K mantenido, cualquier transición se percibe como lag.
 */

interface TopAdjudicatario {
  nombre: string;
  count: number;
  importe: number;
}

interface OrganoDetailResult {
  kpis?: { importe_total?: number };
  top_adjudicatarios?: TopAdjudicatario[];
}

function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-baseline justify-between">
      <h3 className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {children}
      </h3>
      {aside}
    </div>
  );
}

function Fact({
  label,
  value,
  variant = "text",
  color,
}: {
  label: string;
  value: React.ReactNode;
  variant?: "text" | "mono";
  color?: string;
}) {
  return (
    <div className="bg-card px-3 py-2.5">
      <div className="mb-1.5 font-mono text-[8.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          variant === "mono"
            ? "tf-tnum font-mono text-[13px] font-semibold leading-tight"
            : "text-[12.5px] font-medium leading-snug",
        )}
        style={color ? { color } : undefined}
      >
        {value}
      </div>
    </div>
  );
}

/** Adjudicatarios habituales del órgano — la competencia que cabe esperar. */
function ExpectedCompetition({ organo }: { organo: string | null | undefined }) {
  const { data, isLoading } = useQuery<OrganoDetailResult>({
    queryKey: ["radar", "organo", organo],
    queryFn: () =>
      fetchWithAuth<OrganoDetailResult>(
        `/api/v1/analytics/organos/${encodeURIComponent(organo!)}`,
      ),
    enabled: Boolean(organo),
    staleTime: 5 * 60_000,
  });

  if (!organo) return null;

  const total = data?.kpis?.importe_total ?? 0;
  const rivals = (data?.top_adjudicatarios ?? []).slice(0, 3);

  return (
    <>
      <SectionTitle
        aside={
          <span className="text-[10.5px] text-muted-foreground/70">histórico del órgano</span>
        }
      >
        Competencia esperada
      </SectionTitle>
      <div className="flex flex-col gap-1.5 pb-5">
        {isLoading ? (
          <>
            <Skeleton className="h-9 rounded-md" />
            <Skeleton className="h-9 rounded-md" />
            <Skeleton className="h-9 rounded-md" />
          </>
        ) : rivals.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Sin adjudicaciones registradas para este órgano.
          </p>
        ) : (
          rivals.map((rival) => {
            const initials = rival.nombre
              .split(/[\s/]+/)
              .slice(0, 2)
              .map((word) => word[0] ?? "")
              .join("");
            const share = total > 0 ? Math.round((rival.importe / total) * 100) : null;
            return (
              <div
                key={rival.nombre}
                className="flex items-center gap-2.5 rounded-md border border-border/60 bg-card px-2.5 py-2"
              >
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded border border-primary/25 bg-primary/12 font-mono text-[9px] font-semibold text-primary">
                  {initials}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs">{rival.nombre}</span>
                <span className="tf-tnum shrink-0 font-mono text-[11px] text-muted-foreground">
                  {share != null ? `${share}%` : `${rival.count} adj.`}
                </span>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}

export function RadarInspector({
  tender,
  followed,
  onFollow,
  onDismiss,
  onOpenPursuit,
  opening,
  onClose,
}: {
  tender: RadarTender;
  followed: boolean;
  onFollow: () => void;
  onDismiss: () => void;
  onOpenPursuit: () => void;
  opening: boolean;
  onClose?: () => void;
}) {
  const days = daysLeft(tender.fecha_limite);
  const urg = urgency(days);
  const band = tender.band ?? null;
  const desglose = Object.entries(tender.desglose ?? {});

  // Línea de tiempo con las fechas que la API entrega de verdad. Un hito sin
  // fecha no se pinta: un evento vacío se lee como "no ha pasado", que es una
  // afirmación que el dato no sostiene.
  const events = [
    { label: "Publicación", date: tender.fecha_publicacion },
    { label: "Cierre de ofertas", date: tender.fecha_limite },
  ].filter((event) => Boolean(event.date));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-none border-b border-border/60 px-4.5 pb-3.5 pt-4">
        <div className="mb-2.5 flex items-center gap-2">
          <span
            className="inline-flex h-[22px] items-center rounded-md border px-2 text-[10.5px] font-semibold tracking-[0.02em]"
            style={{
              borderColor: bandColorAlpha(band, 0.34),
              background: bandColorAlpha(band, 0.14),
              color: bandColor(band),
            }}
          >
            {band ?? "Sin puntuar"}
          </span>
          <span className="font-mono text-[11px] text-muted-foreground">{tender.id_externo}</span>
          <div className="flex-1" />
          <span className="tf-tnum font-mono text-[22px] font-semibold leading-none">
            {tender.score != null ? Math.round(tender.score) : "—"}
          </span>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar inspector"
              className="tf-pressable ml-1 grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <h2 className="mb-2 font-display text-[15px] font-semibold leading-[1.35] tracking-[-0.01em] text-pretty">
          <Link href={`/detalle?lic=${encodeURIComponent(tender.id_externo)}`} className="hover:underline">
            {tender.titulo}
          </Link>
        </h2>
        {tender.risk_flags?.length ? (
          <ul className="flex flex-wrap gap-1.5">
            {tender.risk_flags.map((flag) => (
              <li
                key={flag}
                className="inline-flex items-center gap-1 rounded border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.12)] px-1.5 py-1 text-[10.5px] text-[hsl(var(--warning))]"
              >
                <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                {flag}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[12.5px] leading-[1.55] text-muted-foreground text-pretty">
            {tender.estado ? `Estado: ${tender.estado}.` : "Sin estado informado."}{" "}
            {days != null
              ? days >= 0
                ? `Quedan ${days} días para el cierre.`
                : `El plazo cerró hace ${Math.abs(days)} días.`
              : "Sin fecha límite publicada."}
          </p>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4.5 pt-4">
        <div className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-[9px] border border-border/60 bg-border/60">
          <Fact label="Órgano" value={tender.organo_contratacion ?? "—"} />
          <Fact label="Importe" value={formatCurrency(tender.importe)} variant="mono" />
          <Fact
            label="Cierre"
            value={days != null ? `${days} días` : formatDate(tender.fecha_limite)}
            variant="mono"
            color={urg.color}
          />
          <Fact label="Tecnología" value={tender.tecnologia ?? tender.ml_tech_principal ?? "—"} />
          <Fact label="CPV" value={tender.cpv ?? "—"} variant="mono" />
          <Fact label="Ámbito" value={tender.ccaa ?? "—"} />
        </div>

        <SectionTitle
          aside={<span className="text-[10.5px] text-muted-foreground/70">ADR-014 · backend</span>}
        >
          Desglose de score
        </SectionTitle>
        <div className="mb-5.5 flex flex-col gap-[7px]">
          {desglose.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              El scoring todavía no ha devuelto desglose para esta licitación.
            </p>
          ) : (
            desglose.map(([key, value]) => (
              <div key={key} className="grid grid-cols-[88px_1fr_30px] items-center gap-2.5">
                <span className="text-[11.5px] text-muted-foreground">
                  {DESGLOSE_LABELS[key] ?? key}
                </span>
                <span className="block h-[5px] overflow-hidden rounded-[3px] bg-muted-foreground/15">
                  <span
                    className="block h-full w-full origin-left bg-linear-to-r from-primary/55 to-primary transition-transform duration-[420ms] ease-out"
                    style={{ transform: `scaleX(${Math.max(0, Math.min(1, value / 100))})` }}
                  />
                </span>
                <span className="tf-tnum text-right font-mono text-[11px] font-medium">
                  {Math.round(value)}
                </span>
              </div>
            ))
          )}
        </div>

        <SectionTitle>Línea de tiempo</SectionTitle>
        <div className="mb-5.5 flex flex-col">
          {events.map((event, index) => (
            <div key={event.label} className="grid grid-cols-[14px_1fr] items-start gap-2.5">
              <div className="flex h-full flex-col items-center">
                <span
                  className={cn(
                    "mt-1 h-[7px] w-[7px] shrink-0 rounded-full",
                    index === 0 ? "bg-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.14)]" : "bg-muted-foreground/35",
                  )}
                />
                {index < events.length - 1 && (
                  <span className="w-px flex-1 bg-muted-foreground/20" />
                )}
              </div>
              <div className="pb-3">
                <div className="text-xs font-medium leading-[1.3]">{event.label}</div>
                <div className="mt-0.5 font-mono text-[10.5px] leading-[1.3] text-muted-foreground">
                  {formatDate(event.date)}
                </div>
              </div>
            </div>
          ))}
        </div>

        <ExpectedCompetition organo={tender.organo_contratacion} />
      </div>

      <div className="flex flex-none items-center gap-[7px] border-t border-border/60 bg-card/80 px-4.5 py-3">
        <button
          type="button"
          onClick={onDismiss}
          className="tf-pressable h-[34px] flex-none rounded-lg border border-border/80 px-3 text-[12.5px] font-medium text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
        >
          Descartar
        </button>
        <button
          type="button"
          onClick={onFollow}
          aria-pressed={followed}
          className={cn(
            "tf-pressable inline-flex h-[34px] flex-none items-center gap-1.5 rounded-lg border px-3 text-[12.5px] font-medium transition-colors",
            followed
              ? "border-primary/50 bg-primary/14 text-primary"
              : "border-border/80 text-muted-foreground hover:text-foreground",
          )}
        >
          <Star className={cn("h-3.5 w-3.5", followed && "fill-current")} aria-hidden="true" />
          {followed ? "Siguiendo" : "Seguir"}
        </button>
        <button
          type="button"
          onClick={onOpenPursuit}
          disabled={opening}
          className="tf-pressable inline-flex h-[34px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-primary/50 bg-linear-to-b from-primary to-[hsl(20_84%_55%)] text-[12.5px] font-semibold text-primary-foreground disabled:opacity-60"
        >
          {opening ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          Abrir oportunidad
        </button>
        {tender.url && (
          <a
            href={tender.url}
            target="_blank"
            rel="noreferrer"
            aria-label={fuenteLinkLabel(tender.fuente, tender.url)}
            className="tf-pressable grid h-[34px] w-[34px] flex-none place-items-center rounded-lg border border-border/80 text-muted-foreground transition-colors hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
    </div>
  );
}
