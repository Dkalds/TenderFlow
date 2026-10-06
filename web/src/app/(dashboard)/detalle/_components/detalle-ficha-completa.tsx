"use client";

import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { PanelError, PanelLoading } from "@/components/console/panel";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fuenteLinkLabel } from "@/lib/fuentes";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { formatNumber } from "@/lib/utils";
import type { PasoDeFicha, PasosDeFicha } from "../_hooks/use-ficha-completa";
import { DetalleFichaCuerpo } from "./detalle-ficha-cuerpo";

function BotonPaso({
  etiqueta,
  atajo,
  onClick,
  children,
}: {
  etiqueta: string;
  atajo: string;
  onClick: (() => void) | null;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* `aria-disabled` y no `disabled`: un botón deshabilitado no recibe
            el puntero y su pista no llegaría a verse. */}
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label={etiqueta}
          aria-disabled={!onClick}
          onClick={onClick ?? undefined}
          className="aria-disabled:opacity-50"
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{`${etiqueta} · ${atajo}`}</TooltipContent>
    </Tooltip>
  );
}

/**
 * La ficha completa de una licitación: ocupa el sitio de la tabla y enseña
 * todas las secciones a la vez, sin pestañas.
 *
 * Se abre desde el inspector («Abrir la ficha completa», `?ficha=completa`) y
 * es la ficha de /detalle por debajo de `md`, donde antes no había ninguna: la
 * tabla mide 1358 px y el inspector no existía en un móvil. Conserva el
 * permalink (`?lic=`), y J/K pasan a la licitación anterior o siguiente de la
 * página de la tabla.
 *
 * La pantalla mide `h-full` y lo que se desplaza es su cuerpo (`relative`,
 * para que los absolutos de dentro no alarguen el documento): la barra de
 * arriba y, en móvil, la del pie quedan siempre a mano.
 */
export function DetalleFichaCompleta({
  idExterno,
  licitacion,
  error,
  onReintentar,
  pasos,
  onIr,
  onVolver,
}: {
  idExterno: string;
  licitacion: LicitacionDetail | null;
  error: unknown;
  onReintentar: () => void;
  /** La posición en la página de la tabla y sus vecinas, para J/K y las flechas. */
  pasos: PasosDeFicha;
  onIr: (paso: PasoDeFicha) => void;
  onVolver: () => void;
}) {
  const { posicion, anterior, siguiente } = pasos;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex min-h-11 flex-none flex-wrap items-center gap-2 border-b border-border/60 px-3.5 py-1.5">
        <Button type="button" variant="ghost" size="sm" onClick={onVolver} className="-ml-1.5">
          <ArrowLeft aria-hidden="true" />
          Volver a la tabla
        </Button>
        <span className="min-w-0 truncate font-mono text-tf-micro text-muted-foreground">{idExterno}</span>
        <div className="flex-1" />
        {posicion && (
          <span className="tf-tnum text-tf-meta text-muted-foreground">
            {formatNumber(posicion.indice + 1)} de {formatNumber(posicion.total)} en esta página
          </span>
        )}
        <div className="flex gap-1.5">
          <BotonPaso etiqueta="Licitación anterior" atajo="K" onClick={anterior ? () => onIr(anterior) : null}>
            <ChevronLeft aria-hidden="true" />
          </BotonPaso>
          <BotonPaso etiqueta="Licitación siguiente" atajo="J" onClick={siguiente ? () => onIr(siguiente) : null}>
            <ChevronRight aria-hidden="true" />
          </BotonPaso>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-y-auto">
        {licitacion ? (
          <DetalleFichaCuerpo key={licitacion.id_externo} licitacion={licitacion} />
        ) : error ? (
          <div className="mx-auto max-w-[640px] px-4 py-8">
            <PanelError title="No se pudo cargar la licitación" error={error} onRetry={onReintentar} />
          </div>
        ) : (
          // El alto de la cabecera y de la tira de cifras: la ficha no salta
          // cuando llega.
          <div className="mx-auto flex max-w-[1360px] flex-col gap-5 px-4 py-5 md:px-6" aria-busy="true">
            <PanelLoading height={96} />
            <PanelLoading height={84} />
            <PanelLoading height={320} />
          </div>
        )}
      </div>

      {licitacion?.url && (
        <div className="flex flex-none border-t border-border/60 bg-card px-4 py-3 md:hidden">
          <Button asChild className="h-11 w-full">
            <a href={licitacion.url} target="_blank" rel="noopener noreferrer">
              {fuenteLinkLabel(licitacion.fuente, licitacion.url)}
              <ExternalLink aria-hidden="true" />
              <AvisoPestanaNueva />
            </a>
          </Button>
        </div>
      )}
    </div>
  );
}
