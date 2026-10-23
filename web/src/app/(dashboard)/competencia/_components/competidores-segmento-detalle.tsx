"use client";

/**
 * El detalle de un segmento elegido en «Concentración por segmento»: quién se
 * lo reparte (`GET /competitive/cuota`) y a qué baja se gana ahí
 * (`GET /competitive/bajas/referencia`).
 *
 * Cada bloque se pide solo si el endpoint sabe filtrar por ese corte
 * (`consultasDeSegmento`); si no, se dice qué corte usar. La referencia sin
 * contratos comparables se dice con palabras, no como un 0 %.
 */

import Link from "next/link";

import { PanelError, ROTULO_DATO } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import {
  consultasDeSegmento,
  nombreSegmento,
  textoBase,
  type ConsultasDeSegmento,
  type HhiSegmento,
  type SegmentoPor,
} from "../_hooks/mercado-segmentos";
import { useBajaReferencia, useCuotaSegmento } from "../_hooks/use-mercado-segmentos";
import { BarraPct } from "./dibujos";

function RepartoSegmento({ consulta }: { consulta: NonNullable<ConsultasDeSegmento["cuota"]> }) {
  const { data, isLoading, error, refetch } = useCuotaSegmento(consulta);
  const items = data?.items ?? [];
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (error) {
    return (
      <PanelError
        variant="inline"
        title="No se pudo cargar quién se reparte el segmento"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (items.length === 0) {
    return <p className="text-tf-meta text-muted-foreground">Sin adjudicaciones con importe en este segmento.</p>;
  }
  return (
    <div>
      <ol aria-label="Quién se reparte el segmento" className="space-y-1.5">
        {items.map((empresa, i) => (
          <li key={empresa.empresa_id ?? `${empresa.empresa}-${i}`} className="text-tf-meta">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
              <span className="flex min-w-0 items-baseline gap-1.5">
                {empresa.empresa_id != null ? (
                  <Link
                    href={`/competencia/empresa/${empresa.empresa_id}`}
                    className="min-w-0 truncate font-medium transition-colors hover:text-primary"
                  >
                    {empresa.empresa ?? "Empresa sin nombre"}
                  </Link>
                ) : (
                  <span className="min-w-0 truncate font-medium">{empresa.empresa ?? "Empresa sin nombre"}</span>
                )}
                {empresa.es_ute === 1 && <Badge variant="outline">UTE</Badge>}
              </span>
              <span className="tf-tnum shrink-0 font-semibold">{formatPercent(empresa.cuota_pct)}</span>
            </div>
            {empresa.cuota_pct != null && <BarraPct pct={empresa.cuota_pct} className="mt-0.5 h-1.5" />}
            <p className="tf-tnum text-tf-micro text-muted-foreground">
              {formatNumber(empresa.contratos)} contratos · {formatCurrency(empresa.importe)}
              {empresa.ofertas_medias != null &&
                ` · ${formatNumber(empresa.ofertas_medias, "es-ES", { decimales: 1 })} ofertas de media`}
            </p>
          </li>
        ))}
      </ol>
      {data?.scope && (
        <p className="mt-2 text-tf-micro text-muted-foreground">
          Cuota sobre {formatNumber(data.scope.denominator_records)} adjudicaciones y{" "}
          {formatCurrency(data.scope.denominator_amount_eur)} del segmento. {data.scope.caveat}
        </p>
      )}
    </div>
  );
}

function ReferenciaSegmento({
  consulta,
}: {
  consulta: NonNullable<ConsultasDeSegmento["referencia"]>;
}) {
  const { data, isLoading, error, refetch } = useBajaReferencia(consulta);
  if (isLoading) return <Skeleton className="h-16 w-full" />;
  if (error) {
    return (
      <PanelError
        variant="inline"
        title="No se pudo cargar la baja de referencia"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (!data || !data.contratos || data.baja_media_pct == null) {
    return (
      <p className="text-tf-meta text-muted-foreground">
        Sin adjudicaciones con presupuesto y baja comparables en este segmento.
      </p>
    );
  }
  return (
    <div className="text-tf-meta">
      <p>
        <span className="tf-tnum text-tf-body font-semibold">{formatPercent(data.baja_media_pct)}</span> de baja media
        {data.baja_min_pct != null && data.baja_max_pct != null && (
          <>
            , de <span className="tf-tnum">{formatPercent(data.baja_min_pct)}</span> a{" "}
            <span className="tf-tnum">{formatPercent(data.baja_max_pct)}</span>
          </>
        )}
        , en {formatNumber(data.contratos)} contratos
        {data.ofertas_medias != null &&
          ` con ${formatNumber(data.ofertas_medias, "es-ES", { decimales: 1 })} ofertas de media`}
        .
      </p>
      <p className="mt-1 text-tf-micro text-muted-foreground">{textoBase(data.base)}</p>
    </div>
  );
}

export function DetalleSegmento({ por, item }: { por: SegmentoPor; item: HhiSegmento }) {
  const consultas = consultasDeSegmento(por, item.segmento);
  const nombre = nombreSegmento(por, item.segmento);
  if (!consultas.cuota && !consultas.referencia) {
    return (
      <p className="text-tf-meta text-muted-foreground">
        Por {por === "tecnologia" ? "tecnología" : "este corte"} no hay desglose de cuota ni de baja de referencia:
        elige un corte por familia CPV, comunidad u órgano.
      </p>
    );
  }
  return (
    <section aria-label={`Detalle de ${nombre}`} className="grid gap-4 md:grid-cols-2">
      <div>
        <p className={cn(ROTULO_DATO, "mb-1.5")}>Quién se lo reparte</p>
        {consultas.cuota ? (
          <RepartoSegmento consulta={consultas.cuota} />
        ) : (
          <p className="text-tf-meta text-muted-foreground">La cuota no se puede pedir por órgano.</p>
        )}
      </div>
      <div>
        <p className={cn(ROTULO_DATO, "mb-1.5")}>A qué baja se gana</p>
        {consultas.referencia ? (
          <ReferenciaSegmento consulta={consultas.referencia} />
        ) : (
          <p className="text-tf-meta text-muted-foreground">
            La baja de referencia se pide por familia CPV u órgano, no por comunidad.
          </p>
        )}
      </div>
    </section>
  );
}
