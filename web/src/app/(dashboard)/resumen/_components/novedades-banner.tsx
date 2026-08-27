"use client";

import Link from "next/link";
import { Info } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, truncate } from "@/lib/utils";
import type { ResumenNovedadesResult } from "@/lib/api-types";

/**
 * Novedades desde la última visita. La muestra de cinco no es decorativa: es
 * lo que convierte «hay 23 nuevas» en algo sobre lo que se puede decidir sin
 * abrir otra pantalla, así que cada línea enlaza a su ficha.
 *
 * `GET /analytics/resumen/novedades` no acepta **ningún** filtro: cuenta contra
 * `last_login` sobre el corpus entero. Estaba en una pantalla llena de chips de
 * ámbito sin decirlo, así que el rótulo lo declara — la misma regla que el
 * aviso de alcance de los paneles vecinos.
 */
export function NovedadesBanner({
  data,
  isLoading,
}: {
  data: ResumenNovedadesResult | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <Skeleton className="mb-4 h-20 w-full rounded-xl" />;
  if (!data) return null;

  if (data.count > 0) {
    return (
      <div className="mb-4 rounded-xl border border-[hsl(var(--info)/0.28)] bg-[hsl(var(--info)/0.05)] px-3.5 py-3">
        <div className="mb-2.5 flex items-center gap-2.5">
          <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-[hsl(var(--info)/0.4)] text-[hsl(var(--info))]">
            <Info className="h-3 w-3" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1 text-[12.5px] font-semibold text-[hsl(var(--info))]">
            {data.count} nuevas licitaciones desde tu última visita
            <span className="ml-1.5 font-normal text-[10.5px] text-[hsl(var(--info)/0.75)]">
              en todo el corpus, sin el ámbito
            </span>
          </span>
          <Link href="/detalle" className="flex-none whitespace-nowrap text-[11.5px] font-medium">
            Ver todas →
          </Link>
        </div>
        <ul className="flex flex-col gap-1.5 pl-8">
          {(data.sample ?? []).slice(0, 5).map((item) => (
            <li key={item.id_externo} className="flex min-w-0 items-baseline gap-3.5">
              <Link
                href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                className="min-w-0 flex-1 truncate text-[11.5px] leading-[1.4] text-[hsl(var(--info))] hover:underline"
              >
                {truncate(item.titulo, 80)}
              </Link>
              {item.importe != null && (
                <span className="tf-tnum flex-none font-mono text-[11px] font-semibold leading-[1.4] text-[hsl(var(--info))]">
                  {formatCurrency(item.importe)}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="mb-4 flex items-center justify-center rounded-xl border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.05)] px-3.5 py-3">
      <span className="text-[12.5px] font-semibold text-[hsl(var(--success))]">Todo al día</span>
    </div>
  );
}
