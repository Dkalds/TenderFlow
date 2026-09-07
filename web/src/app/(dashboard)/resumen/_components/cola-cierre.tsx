"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Clock } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { LicitacionSummary } from "@/lib/api-types";
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
 *    ámbito; `GET /licitaciones` los aplica todos. Mandarle el ámbito entero
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

interface PaginaLicitaciones {
  items: LicitacionSummary[];
  total: number;
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

  const params = useMemo(
    () => ({ ...filtros, ...ventana, limit: String(TECHO), with_total: "true" }),
    [filtros, ventana],
  );

  const hayCola = (total ?? 0) > 0;

  const cola = useQuery<PaginaLicitaciones>({
    queryKey: ["licitaciones", "cola-cierre", params],
    queryFn: () => fetchWithAuth<PaginaLicitaciones>(`/api/v1/licitaciones?${new URLSearchParams(params)}`),
    staleTime: 2 * 60 * 1000,
    // Sin cola que desglosar la petición no aporta nada: la tarjeta ya sabe que
    // va a pintar el estado resuelto.
    enabled: hayCola,
  });

  const filas = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    return proximasACerrar(cola.data?.items ?? [], Date.now());
  }, [cola.data?.items]);

  const recortada = cola.data != null && cola.data.total > cola.data.items.length;
  const cargandoFilas = hayCola && cola.isLoading;

  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border px-3.5 py-3",
        hayCola ? "border-destructive/50 bg-destructive/[0.04]" : "border-border/60 bg-card/70",
        className,
      )}
    >
      <div className="mb-3 flex items-center gap-2.5">
        <span
          className={cn(
            "grid h-6 w-6 flex-none place-items-center rounded-md",
            hayCola
              ? "bg-destructive/14 text-destructive"
              : "bg-muted-foreground/12 text-muted-foreground",
          )}
        >
          <Clock className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="text-[11.5px] font-semibold">Vencen en 48 horas</span>
        {loading ? (
          <Skeleton className="h-5 w-8 rounded" />
        ) : (
          <span
            className={cn(
              "tf-tnum font-mono text-[19px] leading-none font-semibold",
              hayCola ? "text-destructive" : "text-foreground",
            )}
          >
            {formatNumber(total)}
          </span>
        )}
        <div className="flex-1" />
        <Link
          href={href}
          className="text-primary hover:bg-primary/10 group inline-flex h-6 flex-none items-center gap-1.5 rounded-md px-2 text-[11.5px] font-medium transition-colors duration-140 ease-out"
        >
          Ver la cola de cierre
          <ArrowRight
            className="h-3 w-3 transition-transform duration-140 ease-out group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </Link>
      </div>

      {!hayCola && !loading && (
        <div className="flex items-center gap-2 py-3">
          <Check className="h-3.5 w-3.5 flex-none text-[hsl(var(--success))]" aria-hidden="true" />
          <span className="text-muted-foreground text-[11.5px]">
            Nada vence en las próximas 48 horas
          </span>
        </div>
      )}

      {cargandoFilas &&
        Array.from({ length: VISIBLES }, (_, index) => (
          <Skeleton key={index} className="border-border/40 mt-0 h-10 w-full rounded-none border-t" />
        ))}

      {hayCola && !cola.isLoading && (
        <ul className="flex flex-col">
          {filas.map((fila) => (
            <li key={fila.id}>
              <Link
                href={`/detalle?lic=${encodeURIComponent(fila.id)}`}
                className="border-border/40 hover:bg-foreground/[0.04] -mx-1.5 grid h-10 grid-cols-[minmax(0,1fr)_88px_60px] items-center gap-3 rounded-md border-t px-1.5 transition-colors duration-140 ease-out"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[11.5px] leading-[1.3] font-medium">
                    {fila.titulo}
                  </span>
                  <span className="text-muted-foreground block truncate text-[10px] leading-[1.3]">
                    {fila.organo}
                  </span>
                </span>
                <span className="tf-tnum truncate text-right font-mono text-[11px] font-medium">
                  {formatCompactCurrency(fila.importe)}
                </span>
                <span
                  className={cn(
                    "tf-tnum text-right font-mono text-[11.5px] font-semibold",
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
      {hayCola && !cola.isLoading && recortada && (
        <p className="text-muted-foreground mt-2 text-[10px] leading-[1.4]">
          Ordenadas sobre las {formatNumber(cola.data?.items.length)} primeras de{" "}
          {formatNumber(cola.data?.total)}: puede quedar fuera alguna que cierre antes.
        </p>
      )}

      {hayCola && cola.error && (
        <p className="text-muted-foreground mt-2 text-[10px] leading-[1.4]">
          El recuento es correcto, pero no se pudo cargar el desglose.
        </p>
      )}

      <div className="border-border/40 mt-auto flex items-center gap-1.5 border-t pt-2">
        <span className="text-muted-foreground min-w-0 flex-1 truncate font-mono text-[10.5px]">
          {target}
        </span>
      </div>
    </div>
  );
}
