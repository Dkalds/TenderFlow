"use client";

import * as React from "react";
import { ExternalLink, Link2, MessageSquare, X } from "lucide-react";
import { toast } from "sonner";
import { LicitacionAI } from "@/components/licitacion-ai";
import { DocumentosBlock } from "@/components/documentos-block";
import { TecnologiasBlock } from "@/components/tecnologias-block";
import { EventosTimeline } from "@/components/eventos-timeline";
import { PrediccionBajaBlock } from "@/components/prediccion-baja";
import { RecurridoBadge, ResolucionesBlock, useResoluciones } from "@/components/resoluciones-block";
import { StatusBadge } from "@/components/ui/status-badge";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import type { LicitacionDetail } from "@/components/detail-panel";

/**
 * Inspector de la licitación — el mismo contenido del Sheet, en el mismo plano.
 *
 * `DetailPanel` apilaba once bloques dentro de un Sheet modal: para leer los
 * pliegos había que bajar por delante del asistente de IA, y el modal tapaba la
 * tabla de la que venías. Aquí los once bloques se reparten en cinco pestañas y
 * el panel convive con la tabla, así que comparar dos filas es moverse por la
 * lista, no abrir y cerrar.
 *
 * Ningún bloque se ha quedado fuera: Resumen (puntuación + desglose, alertas,
 * predicción de baja, los diez campos, descripción y «Ver en PLACSP»), IA
 * (resumen ejecutivo + chat + «Preguntar»), Eventos, Pliegos (documentos
 * parseados) y Recursos (resoluciones del TACRC). La cabecera conserva estado,
 * badge de recurrida, importe y copiar enlace.
 */

const DESGLOSE_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad",
  riesgo: "Riesgo",
};

type TabKey = "resumen" | "ia" | "eventos" | "pliegos" | "recursos";

const TABS: { key: TabKey; label: string }[] = [
  { key: "resumen", label: "Resumen" },
  { key: "ia", label: "IA" },
  { key: "eventos", label: "Eventos" },
  { key: "pliegos", label: "Pliegos" },
  { key: "recursos", label: "Recursos" },
];

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2.5 font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </h3>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-card px-2.5 py-2">
      <div className="mb-1 font-mono text-[8.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </div>
      <div className="text-[12px] font-medium leading-snug">
        {value ?? <span className="text-muted-foreground">—</span>}
      </div>
    </div>
  );
}

export function DetailInspector({
  licitacion: l,
  onClose,
  className,
}: {
  licitacion: LicitacionDetail;
  onClose: () => void;
  className?: string;
}) {
  const [tab, setTab] = React.useState<TabKey>("resumen");
  // Bump para activar la pestaña «Preguntar» del asistente desde la cabecera.
  const [askSignal, setAskSignal] = React.useState(0);
  const { data: resoluciones } = useResoluciones(l.id_externo);

  // Al cambiar de licitación se vuelve a Resumen: dejar abierta la pestaña de
  // Pliegos de la fila anterior invita a leer el pliego equivocado. Se deriva
  // durante el render (patrón recomendado por React para un valor externo) en
  // vez de con un efecto, que provocaría un render en cascada.
  const [prevId, setPrevId] = React.useState(l.id_externo);
  if (prevId !== l.id_externo) {
    setPrevId(l.id_externo);
    setTab("resumen");
  }

  const copyLink = React.useCallback(async () => {
    const url = `${window.location.origin}/detalle?lic=${encodeURIComponent(l.id_externo)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Enlace copiado al portapapeles");
    } catch {
      toast.error("No se pudo copiar el enlace");
    }
  }, [l.id_externo]);

  const askAI = () => {
    setTab("ia");
    setAskSignal((key) => key + 1);
  };

  const resolucionesCount = resoluciones?.items?.length ?? 0;
  // Sólo se pinta el badge de lo que se puede contar sin pedir un dato extra.
  // Un contador inventado en una pestaña es peor que ningún contador.
  const badges: Partial<Record<TabKey, number>> = { recursos: resolucionesCount };

  return (
    <aside
      aria-label="Ficha de la licitación"
      className={cn("flex min-h-0 flex-1 flex-col bg-card/40", className)}
    >
      <div className="flex-none border-b border-border/60 px-4 pt-3.5">
        <div className="mb-2.5 flex items-center gap-[7px]">
          <StatusBadge value={l.estado} kind="estado" showIcon />
          <RecurridoBadge licitacionId={l.id_externo} />
          <span className="font-mono text-[10.5px] text-muted-foreground">{l.id_externo}</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            title="Cerrar · Esc"
            aria-label="Cerrar ficha"
            className="tf-pressable grid h-6 w-6 place-items-center rounded-md border border-border/60 text-muted-foreground transition-colors duration-140 ease-out hover:border-border hover:text-foreground"
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        </div>

        <h2 className="mb-2.5 font-display text-[15px] font-semibold leading-[1.35] tracking-[-0.01em] text-pretty">
          {l.titulo ?? l.id_externo}
        </h2>

        <div className="mb-3 flex items-center gap-2">
          <span className="tf-tnum font-mono text-[17px] font-semibold leading-none">
            {formatCurrency(l.importe)}
          </span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => void copyLink()}
            title="Copiar enlace ?lic="
            className="tf-pressable inline-flex h-6.5 items-center gap-1.5 rounded-md border border-border/80 px-2.5 text-[11.5px] font-medium text-muted-foreground transition-colors duration-140 ease-out hover:border-primary/45 hover:text-foreground"
          >
            <Link2 className="h-3 w-3" aria-hidden="true" />
            Copiar enlace
          </button>
          <button
            type="button"
            onClick={askAI}
            className="tf-pressable inline-flex h-6.5 items-center gap-1.5 rounded-md border border-primary/35 bg-primary/13 px-2.5 text-[11.5px] font-semibold text-primary transition-colors duration-140 ease-out hover:bg-primary/22"
          >
            <MessageSquare className="h-3 w-3" aria-hidden="true" />
            Preguntar a la IA
          </button>
        </div>

        <div role="tablist" aria-label="Secciones de la ficha" className="flex items-center gap-0.5">
          {TABS.map((item) => {
            const on = tab === item.key;
            const badge = badges[item.key];
            return (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => setTab(item.key)}
                className={cn(
                  "relative inline-flex h-8 items-center gap-1.5 rounded-t-md px-2.5 text-[12px] font-medium transition-colors duration-140 ease-out",
                  on
                    ? "text-foreground after:absolute after:inset-x-1.5 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
                {badge != null && badge > 0 && (
                  <span className="tf-tnum rounded bg-muted-foreground/12 px-1 py-0.5 font-mono text-[9px] font-medium text-muted-foreground">
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4">
        {tab === "resumen" && (
          <div className="pb-6">
            {l.score != null && (
              <>
                <div className="mb-2.5 flex items-center gap-2.5">
                  <SectionTitle>Puntuación</SectionTitle>
                  <div className="flex-1" />
                  <span className="tf-tnum mb-2.5 font-mono text-[15px] font-semibold leading-none">
                    {l.score.toFixed(1)}
                  </span>
                  <span className="mb-2.5">
                    <StatusBadge value={l.band ?? null} kind="band" />
                  </span>
                </div>
                <div
                  role="progressbar"
                  aria-valuenow={Math.min(100, l.score)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Puntuación"
                  className="mb-3.5 block h-1.5 overflow-hidden rounded-[3px] bg-muted-foreground/15"
                >
                  <span
                    className="block h-full w-full origin-left rounded-[3px] bg-primary transition-transform duration-[420ms] ease-out"
                    style={{ transform: `scaleX(${Math.min(100, l.score) / 100})` }}
                  />
                </div>
              </>
            )}

            {l.score_desglose && (
              <div className="mb-4.5 flex flex-col gap-[7px]">
                {Object.entries(l.score_desglose).map(([dim, value]) => (
                  <div key={dim} className="grid grid-cols-[96px_1fr_30px] items-center gap-2.5">
                    <span className="text-[11.5px] text-muted-foreground">
                      {DESGLOSE_LABELS[dim] ?? dim}
                    </span>
                    <span
                      role="progressbar"
                      aria-valuenow={Math.min(100, value)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Puntuación ${dim}`}
                      className="block h-[5px] overflow-hidden rounded-[3px] bg-muted-foreground/15"
                    >
                      <span
                        className="block h-full w-full origin-left bg-linear-to-r from-primary/55 to-primary transition-transform duration-[420ms] ease-out"
                        style={{ transform: `scaleX(${Math.min(100, value) / 100})` }}
                      />
                    </span>
                    <span className="tf-tnum text-right font-mono text-[11px] font-medium">
                      {value.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {l.risk_flags && l.risk_flags.length > 0 && (
              <div className="mb-4.5">
                <SectionTitle>Alertas</SectionTitle>
                <div className="flex flex-wrap gap-1.5">
                  {l.risk_flags.map((flag) => (
                    <span
                      key={flag}
                      className="inline-flex h-[22px] items-center rounded-md border border-destructive/32 bg-destructive/12 px-2 text-[11px] font-medium text-destructive"
                    >
                      {flag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="mb-4.5">
              <PrediccionBajaBlock licitacionId={l.id_externo} />
            </div>

            <SectionTitle>Ficha</SectionTitle>
            <div className="mb-4.5 grid grid-cols-2 gap-px overflow-hidden rounded-[9px] border border-border/60 bg-border/60">
              <Fact label="Órgano" value={l.organo_contratacion} />
              <Fact label="CCAA" value={l.ccaa} />
              <Fact label="Provincia" value={l.provincia} />
              <Fact label="CPV" value={l.cpv} />
              <Fact label="Tipo de contrato" value={l.tipo_contrato} />
              <Fact label="Tecnología" value={l.tecnologia} />
              <Fact label="Publicación" value={formatDate(l.fecha_publicacion)} />
              <Fact label="Fecha límite" value={formatDate(l.fecha_limite)} />
              <Fact label="Inicio" value={formatDate(l.fecha_inicio)} />
              <Fact label="Fin" value={formatDate(l.fecha_fin)} />
            </div>

            <TecnologiasBlock licitacionId={l.id_externo} />

            {l.descripcion && (
              <>
                <SectionTitle>Descripción</SectionTitle>
                <p className="mb-4 whitespace-pre-wrap text-[12.5px] leading-[1.6] text-muted-foreground text-pretty">
                  {l.descripcion}
                </p>
              </>
            )}

            {l.url && (
              <a
                href={l.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-[12.5px] font-medium"
              >
                Ver en PLACSP <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
          </div>
        )}

        {tab === "ia" && (
          <div className="pb-6">
            <LicitacionAI idExterno={l.id_externo} askSignal={askSignal} />
          </div>
        )}

        {tab === "eventos" && (
          <div className="pb-6">
            <EventosTimeline licitacionId={l.id_externo} />
          </div>
        )}

        {tab === "pliegos" && (
          <div className="pb-6">
            <DocumentosBlock licitacionId={l.id_externo} />
          </div>
        )}

        {tab === "recursos" && (
          <div className="pb-6">
            {resolucionesCount > 0 ? (
              <ResolucionesBlock licitacionId={l.id_externo} />
            ) : (
              <div className="rounded-[10px] border border-dashed border-border/60 px-4 py-11 text-center">
                <div className="mb-1.5 text-[13px] font-medium leading-[1.3]">
                  Sin recursos registrados
                </div>
                <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
                  No consta ninguna resolución del TACRC para este expediente.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
