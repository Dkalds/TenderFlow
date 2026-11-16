"use client";

import { useMemo } from "react";
import { EnlaceFicha } from "@/components/ficha/enlace-ficha";
import { EnlaceIr, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useRadar } from "@/hooks/use-radar";
import { useSeguimiento } from "@/hooks/use-seguimiento";
import { useFilters } from "@/lib/filters";
import { cn, daysLeft, EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { claseTextoBanda } from "@/app/(dashboard)/radar/_components/radar-shared";

/** Filas que caben junto a «Tus oportunidades» sin estirar la fila. */
export const VISIBLES_PARA_TI = 5;

/**
 * Para ti — lo primero de la bandeja del Radar, en la pantalla de entrada.
 *
 * El Resumen decía qué vence y qué cambió, pero no qué conviene mirar: eso
 * estaba un clic más allá, en el Radar. Aquí van las primeras señales de la
 * bandeja con su score y su banda, sin triaje: descartar, seguir o abrir la
 * oportunidad siguen siendo del Radar, que es donde está el desglose.
 *
 * Es la misma bandeja que la del Radar, no otra: el mismo ranking
 * (`useRadar`, con la primera tecnología del ámbito, como `useRadarConsola`),
 * las descartadas fuera por el backend y las que ya sigues fuera aquí, con el
 * mismo filtro. El orden es el del backend (ADR-014): no se reordena nada.
 */
export function ParaTi() {
  const { tecnologias } = useFilters();
  const radar = useRadar(tecnologias[0] ?? null);
  const seguidas = useSeguimiento("licitacion").ids;

  const bandeja = useMemo(
    () => (radar.data?.items ?? []).filter((tender) => !seguidas.has(tender.id_externo)),
    [radar.data?.items, seguidas],
  );
  const filas = bandeja.slice(0, VISIBLES_PARA_TI);

  return (
    <Panel className="flex min-w-0 flex-col">
      <section aria-labelledby="resumen-para-ti" className="contents">
        <PanelTitle
          as="h2"
          id="resumen-para-ti"
          title="Para ti"
          hint={
            radar.data
              ? `${formatNumber(bandeja.length)} por revisar en tu bandeja · por score`
              : "lo primero de tu bandeja del Radar"
          }
          actions={<EnlaceIr href="/radar">Abrir el Radar</EnlaceIr>}
          className="mb-2"
        />

        {radar.error ? (
          <PanelError
            variant="inline"
            title="No se pudo cargar tu bandeja"
            error={radar.error}
            onRetry={() => void radar.refetch()}
          />
        ) : radar.isLoading ? (
          Array.from({ length: VISIBLES_PARA_TI }, (_, indice) => (
            <Skeleton key={indice} className="h-12 w-full rounded-none border-t border-divider-subtle" />
          ))
        ) : filas.length === 0 ? (
          <PanelEmpty
            title="Nada por revisar en tu bandeja"
            hint="Aquí salen las licitaciones abiertas que mejor encajan con tu perfil, en cuanto el Radar las puntúa."
          />
        ) : (
          <ul className="flex flex-col">
            {filas.map((tender) => {
              const dias = daysLeft(tender.fecha_limite);
              return (
                <li key={tender.id_externo}>
                  <EnlaceFicha
                    idExterno={tender.id_externo}
                    className="-mx-1.5 grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 rounded-md border-t border-divider-subtle px-1.5 py-2 transition-colors hover:bg-primary-hover active:bg-primary-selected active:duration-0 sm:grid-cols-[48px_minmax(0,1fr)_auto_80px_44px]"
                  >
                    <span className="flex flex-col gap-0.5">
                      <span className={cn("tf-tnum text-tf-lede font-semibold leading-none", claseTextoBanda(tender.band))}>
                        {Math.round(tender.score)}
                      </span>
                      <span className="text-tf-micro font-medium leading-none text-muted-foreground">
                        {tender.band}
                      </span>
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-tf-meta font-medium">{tender.titulo ?? tender.id_externo}</span>
                      <span className="block truncate text-tf-micro text-muted-foreground">
                        {[tender.organo_contratacion, tender.ccaa].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                    <span className="hidden max-w-32 truncate rounded-md bg-muted px-1.5 text-tf-micro font-medium text-muted-foreground sm:inline">
                      {tender.tecnologia ?? ""}
                    </span>
                    <span className="tf-tnum text-right text-tf-meta font-medium">
                      {tender.importe != null ? formatCompactCurrency(tender.importe) : EMPTY}
                    </span>
                    <span className="tf-tnum hidden text-right text-tf-meta text-muted-foreground sm:block">
                      {dias != null && dias >= 0 ? `${dias} d` : EMPTY}
                      <span className="sr-only"> para presentar</span>
                    </span>
                  </EnlaceFicha>
                </li>
              );
            })}
          </ul>
        )}

        {filas.length > 0 && (
          <p className="mt-auto pt-2 text-tf-micro text-muted-foreground">
            {formatNumber(filas.length)} de {formatNumber(bandeja.length)}. Descartar o seguir, en el Radar.
          </p>
        )}
      </section>
    </Panel>
  );
}
