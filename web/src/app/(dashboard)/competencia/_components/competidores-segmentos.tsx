"use client";

/**
 * Concentración por segmento: qué parte del mercado está en pocas manos.
 *
 * La cifra «Concentración (HHI)» de arriba es la del ámbito filtrado entero;
 * esto la abre por segmento —familia CPV, comunidad, órgano o tecnología— con
 * `GET /competitive/hhi`. Al elegir un segmento se ve quién se lo reparte
 * (`/cuota`) y a qué baja se gana ahí (`/bajas/referencia`): concentrado y con
 * baja alta es caro de entrar; concentrado y con baja baja, una oportunidad.
 *
 * El índice es de todo el histórico observado: `/hhi` no admite filtros, y el
 * panel lo dice en vez de dejar que parezca acotado por la barra. Tampoco se
 * pide nada que el endpoint del segmento no sepa filtrar (`consultasDeSegmento`).
 */

import { useState } from "react";

import { Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, EMPTY, formatCurrency, formatNumber } from "@/lib/utils";

import {
  etiquetaHhi,
  nombreSegmento,
  OPCIONES_SEGMENTO,
  ordenarSegmentos,
  type HhiSegmento,
  type OrdenSegmentos,
  type SegmentoPor,
} from "../_hooks/mercado-segmentos";
import { MIN_CONTRATOS_HHI, useHhiSegmentos } from "../_hooks/use-mercado-segmentos";
import { DetalleSegmento } from "./competidores-segmento-detalle";
import { ReglaHhi } from "./regla-hhi";

/** Segmentos que se enseñan: los diez primeros del orden elegido. */
const SEGMENTOS_VISIBLES = 10;

const OPCIONES_ORDEN: readonly { value: OrdenSegmentos; label: string }[] = [
  { value: "concentracion", label: "Más concentrados" },
  { value: "importe", label: "Más importe" },
];

function FilaSegmento({
  por,
  item,
  elegido,
  onElegir,
}: {
  por: SegmentoPor;
  item: HhiSegmento;
  elegido: boolean;
  onElegir: () => void;
}) {
  const nombre = nombreSegmento(por, item.segmento);
  return (
    <li>
      <button
        type="button"
        aria-pressed={elegido}
        onClick={onElegir}
        className={cn(
          "w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60",
          elegido && "bg-primary-selected",
        )}
      >
        <span className="flex min-w-0 items-baseline justify-between gap-3">
          <span className={cn("min-w-0 truncate text-tf-body font-medium", elegido && "text-primary")}>
            {nombre}
          </span>
          <span className="tf-tnum shrink-0 text-tf-body font-semibold">
            {/* Agrupado siempre: es una columna de cifras que se comparan, y
                `es-ES` dejaría «8347» junto a «12.500». */}
            {item.hhi == null ? EMPTY : formatNumber(Math.round(item.hhi), "es-ES", { agruparSiempre: true })}
          </span>
        </span>
        {item.hhi != null && <ReglaHhi hhi={item.hhi} compacta />}
        <span className="mt-0.5 flex flex-wrap justify-between gap-x-3 text-tf-meta text-muted-foreground">
          <span>{item.hhi == null ? "Sin índice" : etiquetaHhi(item.hhi)}</span>
          <span className="tf-tnum">
            {formatNumber(item.empresas)} empresas · {formatNumber(item.contratos)} contratos ·{" "}
            {formatCurrency(item.importe_total)}
          </span>
        </span>
      </button>
    </li>
  );
}

export function CompetidoresSegmentos() {
  const [por, setPor] = useState<SegmentoPor>("cpv");
  const [orden, setOrden] = useState<OrdenSegmentos>("concentracion");
  const [elegido, setElegido] = useState<string | null>(null);
  const { data, isLoading, error, refetch } = useHhiSegmentos(por);

  const items = data?.items ?? [];
  const visibles = ordenarSegmentos(items, orden).slice(0, SEGMENTOS_VISIBLES);
  const abierto = items.find((item) => item.segmento === elegido) ?? null;

  const cambiarCorte = (siguiente: SegmentoPor) => {
    setPor(siguiente);
    // Un segmento de un corte no existe en otro: «72» no es una comunidad.
    setElegido(null);
  };

  return (
    <Panel>
      <PanelTitle
        title="Concentración por segmento"
        hint="todo el histórico observado; no sigue la barra de ámbito"
        actions={
          <span className="flex items-center gap-1.5">
            <GlosarioHint termino="hhi" />
            <Segmented aria-label="Segmentar por" size="xs" value={por} onChange={cambiarCorte} options={OPCIONES_SEGMENTO} />
          </span>
        }
        className="flex-wrap"
      />
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar la concentración por segmento"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : items.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún segmento con masa suficiente"
          hint={`El índice se calcula en segmentos con ${formatNumber(MIN_CONTRATOS_HHI)} contratos adjudicados o más.`}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-tf-meta text-muted-foreground">
              {formatNumber(items.length)} segmentos con {formatNumber(MIN_CONTRATOS_HHI)} contratos o más. Elige uno
              para ver quién se lo reparte y a qué baja.
            </p>
            <Segmented aria-label="Ordenar segmentos" size="xs" value={orden} onChange={setOrden} options={OPCIONES_ORDEN} />
          </div>
          <ul aria-label="Segmentos por concentración" className="grid gap-x-4 gap-y-1 md:grid-cols-2">
            {visibles.map((item) => (
              <FilaSegmento
                key={item.segmento ?? "sin-segmento"}
                por={por}
                item={item}
                elegido={item.segmento === elegido}
                onElegir={() => setElegido((actual) => (actual === item.segmento ? null : (item.segmento ?? null)))}
              />
            ))}
          </ul>
          {abierto && (
            <div className="border-t border-divider pt-3">
              <p className="mb-2 text-tf-body font-semibold">{nombreSegmento(por, abierto.segmento)}</p>
              <DetalleSegmento por={por} item={abierto} />
            </div>
          )}
          {data?.scope && <p className="text-tf-micro text-muted-foreground">{data.scope.caveat}</p>}
        </div>
      )}
    </Panel>
  );
}
