"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { formatCurrency, truncate } from "@/lib/utils";
import type { ResumenNovedadesResult } from "@/lib/api-types";

/**
 * Novedades desde la última visita.
 *
 * Era un bloque de seis líneas —recuento y muestra de cinco fichas— colocado en
 * mitad de la banda urgente, y **repetía** lo que la tabla de publicaciones ya
 * enseñaba dos pantallas más abajo: las mismas licitaciones recientes, con el
 * mismo enlace, contadas dos veces. Ahora el recuento es una línea, va pegado a
 * la tabla que desglosa, y el trabajo de señalar *cuáles* son nuevas lo hace la
 * propia tabla con un punto por fila (`timeline-section.tsx`).
 *
 * La muestra no se tira: sigue debajo, plegada. Con un ámbito activo la tabla
 * está filtrada y el recuento no —ver abajo—, así que puede haber novedades que
 * la tabla no llega a enseñar; ésas sólo se ven aquí.
 *
 * `GET /analytics/resumen/novedades` no acepta **ningún** filtro: cuenta contra
 * `last_login` sobre el corpus entero. Estaba en una pantalla llena de chips de
 * ámbito sin decirlo, así que el rótulo lo declara — la misma regla que el
 * aviso de alcance de los paneles vecinos.
 */

/**
 * La consulta de novedades, compartida por el banner y por la tabla.
 *
 * Los dos la necesitan —el banner el recuento, la tabla el corte `desde` con el
 * que marcar sus filas— y comparten clave, así que React Query las sirve de una
 * sola petición.
 */
export function useNovedades() {
  return useFilteredQuery<ResumenNovedadesResult>(
    ["analytics", "resumen", "novedades"],
    "/api/v1/analytics/resumen/novedades",
    { staleTime: 5 * 60 * 1000 },
  );
}

export function NovedadesBanner({
  data,
  isLoading,
}: {
  data: ResumenNovedadesResult | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <Skeleton className="mb-3.5 h-9 w-full rounded-xl" />;
  if (!data) return null;

  if (data.count > 0) {
    return (
      <div className="mb-3.5 rounded-xl border border-[hsl(var(--info)/0.28)] bg-[hsl(var(--info)/0.05)] px-3.5 py-2">
        <div className="flex items-center gap-2.5">
          <span
            className="h-1.5 w-1.5 flex-none rounded-full bg-[hsl(var(--info))]"
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1 text-[11.5px] leading-[1.4] font-semibold text-[hsl(var(--info))]">
            {data.count} nuevas licitaciones desde tu última visita
            <span className="text-muted-foreground ml-1.5 text-[10.5px] font-normal">
              en todo el corpus, sin el ámbito · las que aparezcan en la tabla van marcadas
            </span>
          </span>
          <Link href="/detalle" className="flex-none text-[11.5px] font-medium whitespace-nowrap">
            Ver todas →
          </Link>
        </div>

        {(data.sample ?? []).length > 0 && (
          <details className="group mt-0.5">
            <summary className="text-muted-foreground hover:text-foreground inline-flex cursor-pointer list-none items-center gap-1 py-1 text-[10.5px] transition-colors duration-140 ease-out">
              <ChevronRight
                className="h-3 w-3 transition-transform duration-140 ease-out group-open:rotate-90"
                aria-hidden="true"
              />
              Ver una muestra
            </summary>
            <ul className="flex flex-col gap-1.5 pt-1 pb-1 pl-4">
              {(data.sample ?? []).slice(0, 5).map((item) => (
                <li key={item.id_externo} className="flex min-w-0 items-baseline gap-3.5">
                  <Link
                    href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                    className="min-w-0 flex-1 truncate text-[11.5px] leading-[1.4] text-[hsl(var(--info))] hover:underline"
                  >
                    {truncate(item.titulo, 80)}
                  </Link>
                  {item.importe != null && (
                    <span className="tf-tnum flex-none font-mono text-[11px] leading-[1.4] font-semibold text-[hsl(var(--info))]">
                      {formatCurrency(item.importe)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    );
  }

  return (
    <div className="mb-3.5 flex items-center gap-2.5 rounded-xl border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.05)] px-3.5 py-2">
      <span className="text-[11.5px] font-semibold text-[hsl(var(--success))]">
        Todo al día · sin novedades desde tu última visita
      </span>
    </div>
  );
}
