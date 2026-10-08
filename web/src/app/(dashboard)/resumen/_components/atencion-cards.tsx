"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  PanelError,
  PanelTitle,
  PULSABLE_SOBRE_TARJETA,
  SUPERFICIE_PANEL,
} from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnnounceOnChange } from "@/components/live-region";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useScopedHref } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatCompactCurrency, formatDate, formatDateTime, formatNumber } from "@/lib/utils";
import type { ResumenHoyResult } from "@/lib/api-types";
import { useNovedades } from "../_hooks/use-novedades";
import { ColaCierre } from "./cola-cierre";

/**
 * Mercado abierto — lo que exige mirar hoy en el mercado.
 *
 * Tres cosas siguen siendo verdad desde la versión anterior, y conviene no
 * perderlas de vista al leer el layout:
 *
 * 1. **El enlace arrastra el ámbito.** Todo destino pasa por `useScopedHref`,
 *    que fusiona ámbito activo y recorte propio: con un chip de CCAA puesto, la
 *    tarjeta contaba Madrid y abría España.
 * 2. **El destino dice si es exacto.** «Grandes en plazo» corta por el P75 que
 *    publica `/resumen/hoy`, que es el del ámbito activo. «Aprox.» queda para
 *    el único caso que no puede ser exacto: un ámbito sin ningún importe, sin
 *    umbral por el que cortar (ADR-014).
 * 3. **El ámbito es el mismo en toda la banda.** `/analytics/resumen/hoy`
 *    aplica la barra de filtros entera, con la semántica del listado. Solo
 *    aplicaba fecha, CCAA y tecnología, y la banda tenía que avisar de qué
 *    chips no estaba mirando.
 *
 * Lo que cambia es el reparto. Las cuatro tarjetas eran del mismo tamaño y
 * decían lo mismo —un número y una flecha—, así que la banda no tenía tesis: la
 * más urgente y la más inerte pesaban igual. Ahora la que tiene plazo ocupa dos
 * tercios y **enseña la cola** (`cola-cierre.tsx`); las dos que se consultan de
 * pasada se apilan en el tercio restante con su deep-link intacto; y «Total
 * activas», que no exige ninguna acción hoy, baja a la tira de contexto, que es
 * donde vive el resto de la foto del ámbito.
 *
 * Las tarjetas no llevan baldosa de icono ni color propio en la cifra: la
 * cifra es el dato (20 px, como un `StatCell`) y el color queda para lo que
 * tiene plazo, que es la cola de cierre.
 */

/** Publicaciones de muestra bajo la cifra de «Nuevas». */
const MUESTRA_NUEVAS = 3;

interface Tarjeta {
  key: string;
  title: string;
  value: number | undefined;
  subtitle: string;
  /** Path con su propio recorte; el ámbito activo se fusiona encima. */
  href: string;
  /** Qué abre de verdad. `exacto: false` ⇒ el listado es más ancho que la cifra. */
  target: string;
  exacto: boolean;
  /** Cada tarjeta carga de su propio endpoint. */
  cargando: boolean;
  /** Lo que la cifra resume, cuando el endpoint lo trae: unas filas de muestra. */
  muestra?: { id: string; titulo: string; importe: number | null }[];
}

function UrgentCard({ card }: { card: Tarjeta }) {
  const scopedHref = useScopedHref();

  return (
    <Link
      href={scopedHref(card.href)}
      className={cn(
        SUPERFICIE_PANEL,
        "flex flex-col px-3.5 py-3 text-left transition-colors hover:border-primary/50 active:duration-0",
        PULSABLE_SOBRE_TARJETA,
      )}
    >
      <span className="mb-1.5 text-tf-meta font-medium">{card.title}</span>
      {card.cargando ? (
        <Skeleton className="h-6 w-16 rounded-sm" />
      ) : (
        <span className="tf-tnum text-tf-title font-semibold">{formatNumber(card.value)}</span>
      )}
      <span className="mt-1 text-tf-meta text-muted-foreground">{card.subtitle}</span>
      {card.muestra && card.muestra.length > 0 && (
        // Texto y no enlaces: la tarjeta entera ya es un enlace.
        <span className="mb-3 mt-2.5 flex flex-col gap-1">
          {card.muestra.map((fila) => (
            <span key={fila.id} className="flex min-w-0 items-center gap-2">
              <span className="h-1.5 w-1.5 flex-none rounded-full bg-primary" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-tf-meta">{fila.titulo}</span>
              <span className="tf-tnum flex-none text-tf-micro font-semibold text-muted-foreground">
                {formatCompactCurrency(fila.importe)}
              </span>
            </span>
          ))}
        </span>
      )}
      <span className="mt-auto flex items-center gap-1.5 border-t border-border/40 pt-2">
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-tf-micro",
            card.exacto ? "text-muted-foreground" : "text-warning",
          )}
        >
          {card.exacto ? card.target : `Aprox. · ${card.target}`}
        </span>
      </span>
    </Link>
  );
}

export function AtencionCards() {
  const scopedHref = useScopedHref();

  // El fallo se pinta aquí mismo (`PanelError`): sin toast encima. Misma
  // clave y mismas opciones en `contexto-strip.tsx`, que lee «Activas».
  const hoy = useFilteredQuery<ResumenHoyResult>(
    ["analytics", "resumen", "hoy"],
    "/api/v1/analytics/resumen/hoy",
    { staleTime: 2 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    undefined,
    true,
  );

  // Deep-link de la cola de cierre: `cierre_desde`/`cierre_hasta` acotan
  // `fecha_limite`, la misma columna sobre la que el KPI cuenta, y
  // `solo_abiertas` es la misma guardia de estado: el KPI ya no cuenta las
  // anuladas o adjudicadas con plazo en la ventana.
  //
  // El recorte es por día y el contador por hora, así que el listado va de las
  // 00:00 de hoy al final de pasado mañana: los mismos dos días, con los
  // extremos redondeados. Es la granularidad que aceptan los parámetros —una
  // fecha en la URL tiene que poder escribirla una persona— y la que mantiene
  // el enlace legible cuando se comparte.
  const vencenHref = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    const ahora = Date.now();
    const desde = new Date(ahora).toISOString().slice(0, 10);
    const hasta = new Date(ahora + 2 * 86400000).toISOString().slice(0, 10);
    return `/detalle?solo_abiertas=true&cierre_desde=${desde}&cierre_hasta=${hasta}`;
  }, []);

  // «En plazo» del contador de grandes: plazo posterior a ahora. El listado
  // corta por día, así que abre también las que cerraron hoy antes de esta
  // hora — el mismo redondeo que la cola de cierre.
  const hoyIso = useMemo(
    // eslint-disable-next-line react-hooks/purity
    () => new Date(Date.now()).toISOString().slice(0, 10),
    [],
  );

  // «Nuevas» cuenta desde tu última visita y en tu ámbito: la misma marca que
  // la banda de arriba, y la misma consulta que marca las filas nuevas de la
  // tabla de publicaciones (`_hooks/use-novedades.ts`). Sustituye a «Nuevas
  // 24h», que contaba otra ventana, y a la línea de novedades de todo el
  // mercado que había encima de la tabla: eran tres ideas de «nuevo».
  const novedades = useNovedades();
  const desde = novedades.data?.desde ?? null;

  const data = hoy.data;
  // `null` solo con un ámbito sin importes: ver el punto 2 de la cabecera.
  const p75 = data?.importe_p75 ?? null;

  // El recuento es el dato central de la pantalla y saltaba en silencio para
  // quien usa lector (hallazgo 5 de la auditoría UX).
  const nuevas = novedades.data ? `${novedades.data.count} nuevas desde tu última visita, ` : "";
  useAnnounceOnChange(
    data
      ? `Mercado abierto: ${data.vencen_48h} vencen en 48 horas, ${nuevas}${data.total_activas} activas.`
      : null,
  );

  const cards: Tarjeta[] = [
    {
      // Se llamaba «Calientes»: el KPI homónimo de la extinta /pipeline-alertas
      // contaba otra cosa (banda del score ≥ 75). El campo del DTO conserva su
      // nombre porque es contrato; lo que se corrige es lo que lee el usuario.
      key: "grandes",
      title: "Grandes en plazo",
      value: data?.calientes,
      // El umbral se dice en cifra: «el 25 % de mayor importe» no dice si eso
      // empieza en 50 k€ o en 2 M€, y depende del ámbito.
      subtitle:
        p75 !== null
          ? `Desde ${formatCompactCurrency(p75)}: el 25 % de mayor importe, abiertas y en plazo`
          : "Del 25 % de mayor importe, abiertas y en plazo",
      href:
        p75 !== null
          ? `/detalle?solo_abiertas=true&cierre_desde=${hoyIso}&importe_min=${p75}`
          : `/detalle?solo_abiertas=true&cierre_desde=${hoyIso}`,
      target:
        p75 !== null
          ? "Abre Detalle: abiertas en plazo del 25 % de mayor importe"
          : "Abre Detalle: abiertas en plazo, sin umbral (el ámbito no trae importes)",
      exacto: p75 !== null,
      cargando: hoy.isLoading,
    },
    {
      key: "nuevas",
      title: "Nuevas",
      value: novedades.data?.count,
      subtitle: novedades.error
        ? "No se pudo comprobar desde tu última visita"
        : desde
          ? `Desde tu última visita, el ${formatDateTime(desde)}`
          : "Desde tu última visita",
      // El listado corta por día: abre también lo publicado ese día antes de
      // la marca. Es el mismo redondeo que la cola de cierre.
      href: desde ? `/detalle?fecha_desde=${desde.slice(0, 10)}` : "/detalle",
      target: desde
        ? `Abre Detalle: publicadas desde el ${formatDate(desde)}`
        : "Abre Detalle: todas las publicaciones",
      exacto: desde !== null || novedades.isLoading,
      cargando: novedades.isLoading,
      muestra: (novedades.data?.sample ?? []).slice(0, MUESTRA_NUEVAS).map((fila) => ({
        id: fila.id_externo,
        titulo: fila.titulo ?? fila.id_externo,
        importe: fila.importe ?? null,
      })),
    },
  ];

  return (
    <section aria-labelledby="resumen-atencion" className="mb-5.5">
      <PanelTitle as="h2" id="resumen-atencion" title="Mercado abierto" hint="hoy" className="mb-2.5" />

      {hoy.error ? (
        <PanelError
          title="No se pudo cargar el estado de hoy"
          error={hoy.error}
          onRetry={() => void hoy.refetch()}
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          <ColaCierre
            className="lg:col-span-2"
            total={data?.vencen_48h}
            loading={hoy.isLoading}
            href={scopedHref(vencenHref)}
            target="Abre Detalle: cierran en 48 h"
          />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {cards.map((card) => (
              <UrgentCard key={card.key} card={card} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
