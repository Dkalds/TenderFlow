"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { EnlaceIr, PanelError, SUPERFICIE_PANEL, TONO_PANEL } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { LicitacionSummary, LicitacionesCursorPage } from "@/lib/api-types";
import { useFiltrosDeResumen } from "./alcance";

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
 *    `/analytics/resumen/hoy`, que sólo aplica cuatro de los siete filtros del
 *    ámbito; `GET /licitaciones/cursor` los aplica todos. Mandarle el ámbito entero
 *    dejaría la lista más estrecha que su propio encabezado —«37» sobre cuatro
 *    filas que sobrevivieron a un chip de estado—, así que se le manda el mismo
 *    recorte que aplicó el contador (`useFiltrosDeResumen`).
 * 2. **Sin `solo_abiertas`.** `vencen_48h` cuenta por `fecha_limite` dentro de
 *    la ventana **sin** guardia de estado (`db/repositories/aggregates.py`, el
 *    `COUNT(*) FILTER` de `vencen_48h`), al revés que `calientes_hoy`. Añadirlo
 *    aquí enseñaría menos filas de las que promete el número.
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
  const filtros = useFiltrosDeResumen();

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
    () => ({ ...filtros, ...ventana, limit: String(TECHO) }),
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
                className="-mx-1.5 grid h-10 grid-cols-[minmax(0,1fr)_88px_60px] items-center gap-3 rounded-md border-t border-border/40 px-1.5 transition-colors hover:bg-primary/5 active:bg-primary/10 active:duration-0"
              >
                <span className="min-w-0">
                  <span className="block truncate text-tf-meta font-medium">{fila.titulo}</span>
                  <span className="block truncate text-tf-micro text-muted-foreground">{fila.organo}</span>
                </span>
                <span className="tf-tnum truncate text-right text-tf-meta font-medium">
                  {formatCompactCurrency(fila.importe)}
                </span>
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
          abriendo la cola completa. */}
      {hayCola && !cola.isLoading && !cola.error && recortada && (
        <p className="mt-2 text-tf-micro text-muted-foreground">
          Ordenadas sobre las {formatNumber(cola.data?.items.length)} primeras de{" "}
          {formatNumber(cola.data?.total)}: puede quedar fuera alguna que cierre antes.
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
