"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, Flame, type LucideIcon, Sparkles } from "lucide-react";
import { PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnnounceOnChange } from "@/components/live-region";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useScopedHref } from "@/lib/filters";
import { cn, formatNumber } from "@/lib/utils";
import type { ResumenHoyResult } from "@/lib/api-types";
import { ColaCierre } from "./cola-cierre";
import { useFiltrosIgnorados } from "./alcance";
import { AvisoAlcance } from "./aviso-alcance";

/**
 * Mercado abierto — lo que exige mirar hoy en el corpus.
 *
 * Tres cosas siguen siendo verdad desde la versión anterior, y conviene no
 * perderlas de vista al leer el layout:
 *
 * 1. **El enlace arrastra el ámbito.** Todo destino pasa por `useScopedHref`,
 *    que fusiona ámbito activo y recorte propio: con un chip de CCAA puesto, la
 *    tarjeta contaba Madrid y abría España.
 * 2. **El destino dice si es exacto.** El `≈` marca el único caso que no puede
 *    serlo: con ámbito activo el P75 se recalcula sobre el subconjunto filtrado
 *    y `/resumen/hoy` no lo publica, así que «Grandes en plazo» abre un listado
 *    más ancho que su cifra y lo declara.
 * 3. **El alcance del endpoint se declara.** `/analytics/resumen/hoy` sólo
 *    aplica fecha, CCAA y tecnología (ver `alcance.ts`).
 *
 * Lo que cambia es el reparto. Las cuatro tarjetas eran del mismo tamaño y
 * decían lo mismo —un número y una flecha—, así que la banda no tenía tesis: la
 * más urgente y la más inerte pesaban igual. Ahora la que tiene plazo ocupa dos
 * tercios y **enseña la cola** (`cola-cierre.tsx`); las dos que se consultan de
 * pasada se apilan en el tercio restante con su deep-link intacto; y «Total
 * activas», que no exige ninguna acción hoy, baja a la tira de contexto, que es
 * donde vive el resto de la foto del ámbito.
 */

const ACCENT = {
  warm: "var(--score-warm)",
  cold: "var(--score-cold)",
} as const;

interface Tarjeta {
  key: string;
  title: string;
  value: number | undefined;
  subtitle: string;
  icon: LucideIcon;
  accent: keyof typeof ACCENT;
  /** Path con su propio recorte; el ámbito activo se fusiona encima. */
  href: string;
  /** Qué abre de verdad. `exacto: false` ⇒ el listado es más ancho que la cifra. */
  target: string;
  exacto: boolean;
}

function UrgentCard({ card, loading }: { card: Tarjeta; loading: boolean }) {
  const scopedHref = useScopedHref();
  const color = `hsl(${ACCENT[card.accent]})`;
  const Icon = card.icon;

  return (
    <Link
      href={scopedHref(card.href)}
      className={cn(
        "group bg-card/70 border-border/60 flex flex-col rounded-xl border px-3.5 py-3 text-left",
        "hover:border-primary/45 transition-[transform,border-color] duration-140 ease-out hover:-translate-y-px",
      )}
    >
      <div className="mb-2 flex items-center gap-2.5">
        <span
          className="grid h-6 w-6 flex-none place-items-center rounded-md"
          style={{ background: `hsl(${ACCENT[card.accent]} / 0.14)`, color }}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="text-[11.5px] font-semibold">{card.title}</span>
        <div className="flex-1" />
        <ArrowRight
          className="text-primary h-3 w-3 flex-none transition-transform duration-140 ease-out group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </div>
      {loading ? (
        <Skeleton className="h-7 w-16 rounded" />
      ) : (
        <div className="tf-tnum font-mono text-[26px] leading-none font-semibold" style={{ color }}>
          {formatNumber(card.value)}
        </div>
      )}
      <div className="text-muted-foreground mt-1.5 text-[11px] leading-[1.45]">{card.subtitle}</div>
      <div className="border-border/40 mt-auto flex items-center gap-1.5 border-t pt-2">
        <span
          className={cn(
            "min-w-0 flex-1 truncate font-mono text-[10.5px]",
            card.exacto ? "text-muted-foreground" : "text-[hsl(var(--warning))]",
          )}
        >
          {card.exacto ? card.target : `≈ ${card.target}`}
        </span>
      </div>
    </Link>
  );
}

export function AtencionCards() {
  const ignorados = useFiltrosIgnorados();
  const scopedHref = useScopedHref();

  const hoy = useFilteredQuery<ResumenHoyResult>(
    ["analytics", "resumen", "hoy"],
    "/api/v1/analytics/resumen/hoy",
    { staleTime: 2 * 60 * 1000 },
    undefined,
    true,
  );

  // Deep-link de «Nuevas 24h»: el listado aplica `fecha_desde` de verdad, así
  // que esta tarjeta sí abre exactamente lo que cuenta.
  const nuevasHref = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    const ayer = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    return `/detalle?fecha_desde=${ayer}`;
  }, []);

  // Deep-link de la cola de cierre: `cierre_desde`/`cierre_hasta` acotan
  // `fecha_limite`, la misma columna sobre la que el KPI cuenta.
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
    return `/detalle?cierre_desde=${desde}&cierre_hasta=${hasta}`;
  }, []);

  const data = hoy.data;
  // `null` cuando el corte no es el global: ver el punto 2 de la cabecera.
  const p75 = data?.importe_p75 ?? null;

  // El recuento es el dato central de la pantalla y saltaba en silencio para
  // quien usa lector (hallazgo 5 de la auditoría UX).
  useAnnounceOnChange(
    data
      ? `Mercado abierto: ${data.vencen_48h} vencen en 48 horas, ${data.nuevas_24h} nuevas en 24 horas, ${data.total_activas} activas.`
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
      subtitle: "Importe ≥ P75, abiertas y en plazo",
      icon: Flame,
      accent: "warm",
      href:
        p75 !== null ? `/detalle?solo_abiertas=true&importe_min=${p75}` : "/detalle?solo_abiertas=true",
      target: p75 !== null ? "/detalle abiertas · importe ≥ P75" : "/detalle abiertas · sin el corte P75",
      exacto: p75 !== null,
    },
    {
      key: "nuevas",
      title: "Nuevas 24h",
      value: data?.nuevas_24h,
      subtitle: "Publicadas hoy",
      icon: Sparkles,
      accent: "cold",
      href: nuevasHref,
      target: "/detalle desde ayer",
      exacto: true,
    },
  ];

  return (
    <section aria-labelledby="resumen-atencion" className="mb-5.5">
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="resumen-atencion" className="text-xs font-semibold">
          Mercado abierto
        </h2>
        <span className="text-muted-foreground text-[10.5px]">
          hoy · el pie de cada tarjeta dice qué listado abre
        </span>
      </div>

      <AvisoAlcance ignorados={ignorados} />

      {hoy.error ? (
        <PanelError
          title="No se pudo cargar el estado de hoy"
          detail={(hoy.error as Error).message}
          onRetry={() => void hoy.refetch()}
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          <ColaCierre
            className="lg:col-span-2"
            total={data?.vencen_48h}
            loading={hoy.isLoading}
            href={scopedHref(vencenHref)}
            target="/detalle · cierra en 48h"
          />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {cards.map((card) => (
              <UrgentCard key={card.key} card={card} loading={hoy.isLoading} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
