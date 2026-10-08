"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { EnlaceIr, PanelError, SUPERFICIE_PANEL, TONO_PANEL } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import { useFilterParams } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { LicitacionSummary, LicitacionesCursorPage } from "@/lib/api-types";

/**
 * «Vencen en 48 horas» — la cola de cierre, no su recuento.
 *
 * Era una tarjeta con un número y una flecha: para saber **qué** vence había
 * que abrir el listado y volver. En una pantalla de entrada cuyo primer trabajo
 * es «¿tengo que hacer algo hoy?», eso convertía la respuesta más urgente en la
 * que más clics costaba. Ahora la tarjeta ocupa dos tercios de la banda y trae
 * las primeras filas ordenadas por lo que queda, así que se decide sin salir.
 *
 * Tres decisiones que no son de maquetación:
 *
 * 1. **La lista mide lo mismo que el número.** El contador sale de
 *    `/analytics/resumen/hoy` y la lista de `GET /licitaciones/cursor`, y los
 *    dos aplican el ámbito entero con la misma semántica, así que se le manda
 *    tal cual. Antes el contador solo aplicaba fecha, CCAA y tecnología, y la
 *    lista tenía que recortar el ámbito para no quedarse más estrecha que su
 *    propio encabezado.
 * 2. **Solo abiertas, en los dos lados.** `vencen_48h` cuenta con la guardia
 *    de estado (`db/repositories/aggregates.py`) y la lista pide
 *    `solo_abiertas`. Contaba sin ella, y una licitación anulada o ya
 *    adjudicada con plazo mañana salía en rojo en una cola a la que nadie se
 *    puede presentar.
 * 3. **Las horas se redondean hacia abajo.** «9 h» y no «9,4 h»: es un plazo
 *    que se agota, y redondear hacia arriba regala tiempo que no existe.
 */

/** Filas visibles. Cuatro entran sin scroll junto a las dos tarjetas apiladas. */
const VISIBLES = 4;

/**
 * Techo de la petición. La ventana son dos días de cierres —en el corpus real,
 * decenas de expedientes—, así que 200 la cubre entera con holgura y deja el
 * orden por plazo bien resuelto en cliente. Si aun así se quedara corto, la
 * tarjeta lo dice en vez de fingir que las cuatro son las más próximas.
 */
const TECHO = 200;

/** La ventana de la cola, en horas: el 100 % de la barra de cada fila. */
const VENTANA_HORAS = 48;

/**
 * Lo que le queda a una fila, como barra sobre las 48 horas: se agota hacia la
 * izquierda. Roja en las últimas 24, como la cifra de horas. SVG con atributos
 * y no un ancho en `style` (scripts/check_inline_styles.py).
 */
function BarraPlazo({ horas }: { horas: number }) {
  const ancho = Math.max(2, Math.min(100, (horas / VENTANA_HORAS) * 100));
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 6"
      preserveAspectRatio="none"
      className="hidden h-1.5 w-full overflow-hidden rounded-full sm:block"
    >
      <rect width="100" height="6" className="fill-border/40" />
      <rect width={ancho} height="6" className={horas <= 24 ? "fill-destructive" : "fill-warning"} />
      {/* La marca de las 24 horas, para leer la barra sin contar. */}
      <rect x="49.6" width="0.8" height="6" className="fill-card" />
    </svg>
  );
}

interface FilaCierre {
  id: string;
  titulo: string;
  organo: string;
  importe: number | null;
  horas: number;
}

/**
 * Horas completas hasta `limite` desde `ahora`, o `null` si la fecha no se
 * puede leer. Exportada por su test: el redondeo es la parte que engaña.
 */
export function horasRestantes(limite: string | null | undefined, ahora: number): number | null {
  if (!limite) return null;
  const ms = Date.parse(limite);
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.floor((ms - ahora) / 3_600_000));
}

/** Ordena por plazo ascendente y recorta a las que caben. */
export function proximasACerrar(
  items: LicitacionSummary[],
  ahora: number,
  visibles = VISIBLES,
): FilaCierre[] {
  return items
    .map((item) => ({
      id: item.id_externo,
      titulo: item.titulo ?? item.id_externo,
      organo: item.organo_contratacion ?? "—",
      importe: item.importe ?? null,
      horas: horasRestantes(item.fecha_limite, ahora),
    }))
    .filter((fila): fila is FilaCierre => fila.horas !== null)
    .sort((a, b) => a.horas - b.horas)
    .slice(0, visibles);
}

export function ColaCierre({
  total,
  loading,
  href,
  target,
  className,
}: {
  /** Recuento autoritativo, el de `/resumen/hoy`. La lista sólo lo desglosa. */
  total: number | undefined;
  loading: boolean;
  href: string;
  /** Qué abre `href`, en claro. Misma regla que el pie de las tarjetas vecinas. */
  target: string;
  className?: string;
}) {
  const filtros = useFilterParams();

  // Ventana de la consulta: de hoy a pasado mañana. El recorte es por día y el
  // contador por hora —los parámetros aceptan fecha, no timestamp—, así que la
  // petición trae algún cierre de más y el orden por `fecha_limite` lo coloca
  // al final, donde no estorba.
  const ventana = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    const ahora = Date.now();
    return {
      cierre_desde: new Date(ahora).toISOString().slice(0, 10),
      cierre_hasta: new Date(ahora + 2 * 86400000).toISOString().slice(0, 10),
    };
  }, []);

  // Sin `with_total`: para saber si la lista se quedó corta basta `has_more`
  // del cursor, sin pagar un COUNT(*). El listado por offset que esto usaba
  // se retira (RFC 2026-09-06); el cursor acepta los mismos filtros.
  const params = useMemo(
    () => ({ ...filtros, ...ventana, solo_abiertas: "true", limit: String(TECHO) }),
    [filtros, ventana],
  );

  const hayCola = (total ?? 0) > 0;

  const cola = useQuery<LicitacionesCursorPage>({
    queryKey: ["licitaciones", "cola-cierre", params],
    queryFn: () =>
      fetchWithAuth<LicitacionesCursorPage>(
        `/api/v1/licitaciones/cursor?${new URLSearchParams(params)}`,
      ),
    staleTime: 2 * 60 * 1000,
    // Sin cola que desglosar la petición no aporta nada: la tarjeta ya sabe que
    // va a pintar el estado resuelto.
    enabled: hayCola,
    // El fallo del desglose se dice dentro de la tarjeta: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const filas = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    return proximasACerrar(cola.data?.items ?? [], Date.now());
  }, [cola.data?.items]);

  const recortada = cola.data?.has_more === true;
  const cargandoFilas = hayCola && cola.isLoading;

  return (
    <div
      className={cn(
        SUPERFICIE_PANEL,
        "flex flex-col px-3.5 py-3",
        // Con cola, el borde avisa; la cifra en rojo dice cuánto. Sin baldosa
        // de icono ni relleno tintado: el énfasis de un panel es su borde.
        hayCola && TONO_PANEL.danger,
        className,
      )}
    >
      <div className="mb-3 flex items-baseline gap-2.5">
        <span className="text-tf-meta font-medium">Vencen en 48 horas</span>
        {loading ? (
          <Skeleton className="h-5 w-8 self-center rounded-sm" />
        ) : (
          <span
            className={cn(
              "tf-tnum text-tf-title font-semibold leading-none",
              hayCola ? "text-destructive" : "text-foreground",
            )}
          >
            {formatNumber(total)}
          </span>
        )}
        <div className="flex-1" />
        <EnlaceIr href={href} className="flex-none">
          Ver la cola de cierre
        </EnlaceIr>
      </div>

      {!hayCola && !loading && (
        <div className="flex items-center gap-2 py-3">
          <Check className="h-3.5 w-3.5 flex-none text-success" aria-hidden="true" />
          <span className="text-tf-meta text-muted-foreground">Nada vence en las próximas 48 horas</span>
        </div>
      )}

      {cargandoFilas &&
        Array.from({ length: VISIBLES }, (_, index) => (
          <Skeleton key={index} className="mt-0 h-10 w-full rounded-none border-t border-border/40" />
        ))}

      {hayCola && !cola.isLoading && !cola.error && (
        <ul className="flex flex-col">
          {filas.map((fila) => (
            <li key={fila.id}>
              <Link
                href={`/detalle?lic=${encodeURIComponent(fila.id)}`}
                className="-mx-1.5 grid h-10 grid-cols-[minmax(0,1fr)_88px_60px] items-center gap-3 rounded-md border-t border-border/40 px-1.5 transition-colors hover:bg-primary/5 active:bg-primary/10 active:duration-0 sm:grid-cols-[minmax(0,1fr)_88px_minmax(80px,160px)_60px]"
              >
                <span className="min-w-0">
                  <span className="block truncate text-tf-meta font-medium">{fila.titulo}</span>
                  <span className="block truncate text-tf-micro text-muted-foreground">{fila.organo}</span>
                </span>
                <span className="tf-tnum truncate text-right text-tf-meta font-medium">
                  {formatCompactCurrency(fila.importe)}
                </span>
                <BarraPlazo horas={fila.horas} />
                <span
                  className={cn(
                    "tf-tnum text-right text-tf-meta font-semibold",
                    fila.horas <= 24 ? "text-destructive" : "text-foreground",
                  )}
                >
                  {fila.horas} h
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {/* El desglose no puede prometer que son «las cuatro más próximas» si no
          se trajo la ventana entera: se dice, y el enlace de arriba sigue
          abriendo la cola completa. Sin «de N»: la petición va sin
          `with_total`, así que el total del cursor llega vacío y el recuento
          autoritativo ya está en la cabecera. */}
      {hayCola && !cola.isLoading && !cola.error && recortada && (
        <p className="mt-2 text-tf-micro text-muted-foreground">
          Ordenadas sobre las {formatNumber(cola.data?.items.length)} primeras: puede quedar fuera
          alguna que cierre antes.
        </p>
      )}

      {hayCola && cola.error && (
        <PanelError
          variant="inline"
          title="No se pudo cargar el desglose"
          message="El recuento de arriba es correcto; lo que falta es la lista."
          error={cola.error}
          onRetry={() => void cola.refetch()}
        />
      )}

      <div className="mt-auto flex items-center gap-1.5 border-t border-border/40 pt-2">
        <span className="min-w-0 flex-1 truncate text-tf-micro text-muted-foreground">{target}</span>
      </div>
    </div>
  );
}
