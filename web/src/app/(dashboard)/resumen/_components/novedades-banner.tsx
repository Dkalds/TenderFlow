"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Aviso, EnlaceIr } from "@/components/console/panel";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet } from "@/lib/api-client";
import { analyticsKeys } from "@/lib/query-keys";
import { formatCurrency, formatDateTime, formatNumber, truncate } from "@/lib/utils";
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
 * `GET /analytics/resumen/novedades` no acepta **ningún** filtro: cuenta sobre
 * todo el mercado. Estaba en una pantalla llena de chips de ámbito sin decirlo,
 * así que la línea lo declara («sin tu ámbito»).
 *
 * **La última visita es la de la banda de arriba** (`desde-ultima-visita.tsx`):
 * el backend lee la misma marca y devuelve el mismo `desde`, que aquí se dice
 * con su fecha. Antes contaba contra `users.last_login`, una columna que no
 * existe, y esta línea decía «Todo al día» siempre, sin haber mirado nada.
 */

/**
 * La consulta de novedades, compartida por el banner y por la tabla.
 *
 * Los dos la necesitan —el banner el recuento, la tabla el corte `desde` con el
 * que marcar sus filas— y comparten clave, así que React Query las sirve de una
 * sola petición.
 */
export function useNovedades() {
  // `useQuery` y no `useFilteredQuery`: el endpoint ignora el ámbito, y con la
  // clave filtrada cada chip abría otra entrada de caché para la misma respuesta.
  return useQuery<ResumenNovedadesResult>({
    queryKey: analyticsKeys.novedades,
    queryFn: () => apiGet("/api/v1/analytics/resumen/novedades"),
    // Mismo criterio que la banda de arriba: el corte se mueve con «Marcar
    // todo como visto», que invalida las dos.
    staleTime: 60_000,
  });
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

  // El backend siempre publica el corte; sin él (un despliegue viejo) se dice
  // «tu última visita» en vez de inventar una fecha.
  const desde = data.desde ? `el ${formatDateTime(data.desde)}` : "tu última visita";

  if (data.count > 0) {
    return (
      <Aviso
        tone="info"
        className="mb-3.5"
        title={`${formatNumber(data.count)} ${data.count === 1 ? "licitación nueva" : "licitaciones nuevas"} desde ${desde}`}
        action={<EnlaceIr href="/detalle">Ver todas</EnlaceIr>}
      >
        <span className="text-muted-foreground">En todo el mercado, sin tu ámbito · en la tabla van marcadas.</span>

        {(data.sample ?? []).length > 0 && (
          <details className="group mt-0.5">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 py-1 text-tf-micro text-muted-foreground transition-colors hover:text-foreground">
              <ChevronRight
                className="h-3 w-3 transition-[rotate] group-open:rotate-90"
                aria-hidden="true"
              />
              Ver una muestra
            </summary>
            <ul className="flex flex-col gap-1.5 pt-1 pb-1 pl-4">
              {(data.sample ?? []).slice(0, 5).map((item) => (
                <li key={item.id_externo} className="flex min-w-0 items-baseline gap-3.5">
                  <Link
                    href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                    className="min-w-0 flex-1 truncate hover:underline"
                  >
                    {truncate(item.titulo, 80)}
                  </Link>
                  {item.importe != null && (
                    <span className="tf-tnum flex-none font-semibold">{formatCurrency(item.importe)}</span>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Aviso>
    );
  }

  return (
    <Aviso tone="success" className="mb-3.5">
      Todo al día: ninguna licitación nueva en el mercado desde {desde}.
    </Aviso>
  );
}
