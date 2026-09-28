"use client";

/**
 * F5.4 — «Qué cambió desde tu última visita».
 *
 * El Resumen ya tenía novedades **de mercado** (`novedades-banner.tsx`): qué
 * expedientes nuevos hay en el corpus. Esta banda responde otra pregunta —qué
 * se ha movido en **lo mío**: los expedientes que sigo, sus pliegos y
 * recursos, y las oportunidades de mi equipo— y la calcula el backend
 * (`GET /analytics/resumen/desde-mi-ultima-visita`), que fusiona las cuatro
 * fuentes y ya trae cada línea redactada. Aquí sólo se pinta.
 *
 * Tres reglas que vienen del endpoint y la pantalla respeta:
 *
 * - **Cero ítems es una banda, no un hueco.** «Sin novedades desde el jueves»
 *   confirma que el producto estaba mirando; una banda ausente se lee como que
 *   la pieza está rota.
 * - **La marca se dice.** `desde` viaja en la respuesta para poder escribir
 *   desde cuándo, en vez de «recientemente».
 * - **El recorte se declara.** Con `ventana_recortada` la última visita es
 *   anterior al tope del backend y la banda empieza en `desde`, no en ella.
 *
 * Sin organización activa el backend sólo mira lo seguido, no el equipo; se
 * pide con la organización activa para que las oportunidades entren.
 *
 * «Marcar todo como visto» mueve la marca a ahora
 * (`POST …/desde-mi-ultima-visita/visto`) sin marcar ninguna notificación
 * concreta, y vuelve a pedir la banda: lo que se ve después es «sin cambios
 * desde ahora», que confirma que la marca se movió. Solo se ofrece con cambios
 * que marcar.
 */

import * as React from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { SUPERFICIE_PANEL } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { registrarEvento } from "@/lib/analytics";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { analyticsKeys } from "@/lib/query-keys";
import { cn, formatDateTime, formatRelativeTime, truncate } from "@/lib/utils";

type NovedadesDesdeUltimaVisita = Schemas["NovedadesDesdeUltimaVisita"];
type Novedad = Schemas["Novedad"];
type VisitaMarcada = Schemas["VisitaMarcada"];

/** «Marcar todo como visto»: mueve la marca y vuelve a pedir la banda. */
function useMarcarVisto() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiMutate<VisitaMarcada>("POST", "/api/v1/analytics/resumen/desde-mi-ultima-visita/visto"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["analytics", "resumen", "desde-mi-ultima-visita"] }),
    onError: () => toast.error("No se pudo marcar como visto. Vuelve a intentarlo."),
  });
}

/** Líneas visibles sin desplegar: las que caben en la primera pantalla. */
const VISIBLES = 4;

function useDesdeUltimaVisita() {
  const organizationId = useActiveOrganizationId();
  return useQuery<NovedadesDesdeUltimaVisita>({
    queryKey: analyticsKeys.desdeUltimaVisita(organizationId),
    queryFn: () =>
      apiGet("/api/v1/analytics/resumen/desde-mi-ultima-visita", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    // El endpoint no cachea a propósito (es un diff por usuario y marca). En
    // cliente basta con no repetirlo en cada re-montaje de la pantalla.
    staleTime: 60_000,
  });
}

function LineaNovedad({ novedad }: { novedad: Novedad }) {
  const contenido = (
    <>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-tf-meta font-medium">{truncate(novedad.titulo, 110)}</span>
        {novedad.detalle && (
          <span className="block truncate text-tf-micro text-muted-foreground">{novedad.detalle}</span>
        )}
      </span>
      {novedad.cuando && (
        <time dateTime={novedad.cuando} className="flex-none whitespace-nowrap text-tf-micro text-muted-foreground">
          {formatRelativeTime(novedad.cuando)}
        </time>
      )}
    </>
  );
  return (
    <li>
      {novedad.licitacion_id ? (
        <Link
          href={`/detalle?lic=${encodeURIComponent(novedad.licitacion_id)}`}
          className="flex items-baseline gap-3 rounded-md px-1.5 py-1 transition-colors hover:bg-primary/5 active:bg-primary/10 active:duration-0"
        >
          {contenido}
        </Link>
      ) : (
        <div className="flex items-baseline gap-3 px-1.5 py-1">{contenido}</div>
      )}
    </li>
  );
}

export function DesdeUltimaVisita() {
  const { data, isPending, isError } = useDesdeUltimaVisita();
  const marcarVisto = useMarcarVisto();
  const medida = React.useRef(false);

  React.useEffect(() => {
    if (!data || medida.current) return;
    medida.current = true;
    registrarEvento("espacio_abierto", {
      espacio: "resumen",
      origen: "pantalla",
      banda: "desde_ultima_visita",
    });
  }, [data]);

  if (isPending) return <Skeleton className="mb-3.5 h-11 w-full rounded-xl" />;
  // Un fallo no tumba el Resumen: la banda es un añadido sobre lo que ya había.
  if (isError || !data) return null;

  const items = data.items ?? [];
  const desde = formatDateTime(data.desde);

  return (
    <section aria-labelledby="desde-ultima-visita-titulo" className={cn(SUPERFICIE_PANEL, "mb-3.5 px-3.5 py-2.5")}>
      <div className="flex items-center gap-2.5">
        <h2 id="desde-ultima-visita-titulo" className="min-w-0 text-tf-body font-semibold">
          {items.length > 0
            ? `${items.length} ${items.length === 1 ? "cambio" : "cambios"} en lo que sigues desde el ${desde}`
            : `Sin cambios en lo que sigues desde el ${desde}`}
        </h2>
        {items.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => marcarVisto.mutate()}
            disabled={marcarVisto.isPending}
            className="ml-auto flex-none text-muted-foreground"
          >
            {marcarVisto.isPending ? "Marcando…" : "Marcar todo como visto"}
          </Button>
        )}
      </div>
      {data.ventana_recortada && (
        <p className="mt-0.5 text-tf-micro text-muted-foreground">
          Tu última visita es anterior a esa fecha: no se mira más atrás.
        </p>
      )}

      {items.length > 0 && (
        <ul className="mt-1.5 flex flex-col">
          {items.slice(0, VISIBLES).map((novedad, indice) => (
            <LineaNovedad key={`${novedad.subtipo}-${novedad.licitacion_id ?? ""}-${indice}`} novedad={novedad} />
          ))}
        </ul>
      )}

      {items.length > VISIBLES && (
        <details className="group">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 py-1 text-tf-micro text-muted-foreground transition-colors hover:text-foreground">
            <ChevronRight className="h-3 w-3 transition-[rotate] group-open:rotate-90" aria-hidden="true" />
            Ver {items.length - VISIBLES} más
          </summary>
          <ul className="flex flex-col">
            {items.slice(VISIBLES).map((novedad, indice) => (
              <LineaNovedad
                key={`${novedad.subtipo}-${novedad.licitacion_id ?? ""}-${indice + VISIBLES}`}
                novedad={novedad}
              />
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
