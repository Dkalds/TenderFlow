"use client";

/**
 * F5.4 — «Qué cambió desde tu última visita».
 *
 * El Resumen ya tenía novedades **de mercado** (la tarjeta «Nuevas» de
 * «Mercado abierto», `_hooks/use-novedades.ts`): qué expedientes nuevos hay en
 * el ámbito. Esta banda responde otra pregunta —qué
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
import { estiloSubtipo, repartoPorSubtipo, type TramoReparto } from "./novedades-subtipos";

type NovedadesDesdeUltimaVisita = Schemas["NovedadesDesdeUltimaVisita"];
type Novedad = Schemas["Novedad"];
type VisitaMarcada = Schemas["VisitaMarcada"];

/**
 * «Marcar todo como visto»: mueve la marca y vuelve a pedir lo que cuelga de
 * ella — esta banda y las licitaciones nuevas del mercado
 * (`_hooks/use-novedades.ts`: la tarjeta «Nuevas» y los puntos de la tabla),
 * que cuentan desde la misma última visita.
 */
export function useMarcarVisto() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiMutate<VisitaMarcada>("POST", "/api/v1/analytics/resumen/desde-mi-ultima-visita/visto"),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["analytics", "resumen", "desde-mi-ultima-visita"] }),
        queryClient.invalidateQueries({ queryKey: analyticsKeys.novedades }),
      ]),
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

/**
 * Barra del reparto por clase de cambio, con los recuentos que trae
 * `por_subtipo`. SVG con atributos y no anchos en `style`: un estilo en línea
 * más alejaría quitar `'unsafe-inline'` de `style-src`
 * (scripts/check_inline_styles.py). Lo que dice la barra lo dice también la
 * leyenda en texto, así que la barra es decorativa para el lector.
 */
function BarraReparto({ tramos, total }: { tramos: TramoReparto[]; total: number }) {
  return (
    <svg
      aria-hidden="true"
      viewBox={`0 0 ${total} 1`}
      preserveAspectRatio="none"
      className="h-2 w-full overflow-hidden rounded-full"
    >
      {tramos.map((tramo) => (
        <rect
          key={tramo.clave}
          x={tramo.inicio}
          width={tramo.n}
          height="1"
          fill={tramo.color}
          className="stroke-card"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

function LeyendaReparto({ tramos }: { tramos: TramoReparto[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3.5 gap-y-1">
      {tramos.map((tramo) => (
        <li key={tramo.clave} className="inline-flex items-center gap-1.5 text-tf-meta text-muted-foreground">
          <svg aria-hidden="true" viewBox="0 0 8 8" className="h-2 w-2 flex-none">
            <circle cx="4" cy="4" r="4" fill={tramo.color} />
          </svg>
          {tramo.etiqueta}
          <span className="tf-tnum font-semibold text-foreground">{tramo.n}</span>
        </li>
      ))}
    </ul>
  );
}

function LineaNovedad({ novedad }: { novedad: Novedad }) {
  // El icono va del color de su tramo en la barra: la línea y el tramo se leen juntos.
  const { icono: Icono, color } = estiloSubtipo(novedad.subtipo);
  const contenido = (
    <>
      <Icono className="h-3.5 w-3.5 flex-none" color={color} aria-hidden="true" />
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
          className="flex items-center gap-2.5 rounded-md px-1.5 py-1 transition-colors hover:bg-primary/5 active:bg-primary/10 active:duration-0"
        >
          {contenido}
        </Link>
      ) : (
        <div className="flex items-center gap-2.5 px-1.5 py-1">{contenido}</div>
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

  const tramos = repartoPorSubtipo(data.por_subtipo);
  const hayCambios = items.length > 0;

  return (
    <section aria-labelledby="desde-ultima-visita-titulo" className={cn(SUPERFICIE_PANEL, "mb-3.5 px-4 py-3.5")}>
      {/* Dos columnas en escritorio: a la izquierda cuánto y de qué clase, a la
          derecha qué en concreto. Sin cambios, una sola línea que lo dice. */}
      <div className={cn("grid gap-x-8 gap-y-3", hayCambios && "lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]")}>
        <div className="flex min-w-0 flex-col gap-2.5">
          <h2 id="desde-ultima-visita-titulo" className="font-display text-tf-lede font-semibold">
            {hayCambios
              ? `${items.length} ${items.length === 1 ? "cambio" : "cambios"} en lo que sigues desde el ${desde}`
              : `Sin cambios en lo que sigues desde el ${desde}`}
          </h2>
          {data.ventana_recortada && (
            <p className="-mt-1.5 text-tf-micro text-muted-foreground">
              Tu última visita es anterior a esa fecha: no se mira más atrás.
            </p>
          )}
          {hayCambios && tramos.length > 0 && (
            <>
              <BarraReparto tramos={tramos} total={items.length} />
              <LeyendaReparto tramos={tramos} />
            </>
          )}
          {hayCambios && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => marcarVisto.mutate()}
              disabled={marcarVisto.isPending}
              className="-ml-2.5 self-start text-muted-foreground"
            >
              {marcarVisto.isPending ? "Marcando…" : "Marcar todo como visto"}
            </Button>
          )}
        </div>

        {hayCambios && (
          <div className="min-w-0">
            <ul className="flex flex-col">
              {items.slice(0, VISIBLES).map((novedad, indice) => (
                <LineaNovedad key={`${novedad.subtipo}-${novedad.licitacion_id ?? ""}-${indice}`} novedad={novedad} />
              ))}
            </ul>

            {items.length > VISIBLES && (
              <details className="group">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1 px-1.5 py-1 text-tf-micro text-muted-foreground transition-colors hover:text-foreground">
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
          </div>
        )}
      </div>
    </section>
  );
}
