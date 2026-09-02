"use client";

/**
 * El expediente dentro de la ficha de la oportunidad.
 *
 * La mitad del diagnóstico de producto de 2026-09: el contenido de la
 * licitación (órgano, CPV, plazos, pliegos, cronología, recursos) vivía sólo
 * en el inspector de `/detalle`, y la oportunidad —la pantalla donde se
 * decide— sólo tenía un enlace «Ver anuncio original». Se decidía en una
 * pantalla mirando lo que estaba en la otra.
 *
 * No duplica nada: reutiliza los mismos bloques que monta el inspector
 * (`DocumentosBlock`, `EventosTimeline`, `ResolucionesBlock`,
 * `TecnologiasBlock`), que traen su propio estado de carga, error y vacío. El
 * asistente IA **no** entra aquí: es una superficie con su propio coste y su
 * propio contrato, y vive en `/detalle`.
 */
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { DocumentosBlock } from "@/components/documentos-block";
import { EventosTimeline } from "@/components/eventos-timeline";
import { ResolucionesBlock } from "@/components/resoluciones-block";
import { TecnologiasBlock } from "@/components/tecnologias-block";
import { Panel, PanelError, PanelLoading, SectionTitle } from "@/components/console/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { useLicitacion } from "@/hooks/use-licitacion";
import { EMPTY, formatCurrency, formatDate } from "@/lib/utils";
import { fuenteLinkLabel } from "@/lib/fuentes";

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-card px-3 py-2">
      <div className="mb-0.5 font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </div>
      <div className="text-[12.5px] leading-[1.35]">{value || EMPTY}</div>
    </div>
  );
}

export function ExpedientePanel({ licitacionId }: { licitacionId: string }) {
  const { data: licitacion, isLoading, error, refetch } = useLicitacion(licitacionId);

  if (isLoading) return <PanelLoading height={320} />;

  if (error || !licitacion) {
    return (
      <PanelError
        title="No se pudo cargar el expediente"
        detail={error instanceof Error ? error.message : "No encontrado"}
        onRetry={() => void refetch()}
        height={320}
      />
    );
  }

  const l = licitacion;

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex flex-col gap-4">
        <Panel>
          <SectionTitle
            aside={l.estado ? <StatusBadge value={l.estado} kind="estado" showIcon /> : undefined}
          >
            Ficha del expediente
          </SectionTitle>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[9px] border border-border/60 bg-border/60">
            <Fact label="Órgano" value={l.organo_contratacion} />
            <Fact label="Importe" value={l.importe != null ? formatCurrency(l.importe) : null} />
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

          {l.descripcion && (
            <div className="mt-4">
              <SectionTitle>Descripción</SectionTitle>
              <p className="whitespace-pre-wrap text-[12.5px] leading-[1.6] text-pretty text-muted-foreground">
                {l.descripcion}
              </p>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
            {l.url && (
              <a
                href={l.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-[12.5px] font-medium"
              >
                {fuenteLinkLabel(l.fuente, l.url)}
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
            <Link
              href={`/detalle?lic=${encodeURIComponent(licitacionId)}`}
              className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground hover:text-foreground"
            >
              Abrir en Detalle
            </Link>
          </div>
        </Panel>

        <Panel>
          <SectionTitle>Pliegos y documentos</SectionTitle>
          {/* `fichaUrl` da salida cuando el enlace directo al adjunto ya no
              responde (los tokens de PLACSP rotan) o cuando no hemos indexado
              ningún pliego todavía. */}
          <DocumentosBlock licitacionId={licitacionId} fichaUrl={l.url} />
        </Panel>
      </div>

      <div className="flex flex-col gap-4">
        <Panel>
          <SectionTitle>Señal tecnológica</SectionTitle>
          <TecnologiasBlock licitacionId={licitacionId} />
        </Panel>

        <Panel>
          <SectionTitle>Cronología</SectionTitle>
          <EventosTimeline licitacionId={licitacionId} />
        </Panel>

        <Panel>
          <SectionTitle>Recursos</SectionTitle>
          {/* `ResolucionesBlock` no renderiza nada si no hay resoluciones del
              TACRC, que es el caso normal: el rótulo se queda con el vacío
              declarado debajo. */}
          <ResolucionesBlock licitacionId={licitacionId} />
          <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
            Solo aparecen aquí las resoluciones del TACRC publicadas para este expediente.
          </p>
        </Panel>
      </div>
    </div>
  );
}
