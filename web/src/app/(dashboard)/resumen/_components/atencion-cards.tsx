"use client";

import Link from "next/link";
import { useMemo } from "react";
import { Activity, ArrowRight, Clock, Flame, type LucideIcon, Sparkles } from "lucide-react";
import { Stagger } from "@/components/motion";
import { PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnnounceOnChange } from "@/components/live-region";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useScopedHref } from "@/lib/filters";
import { cn, formatNumber } from "@/lib/utils";
import type { ResumenNovedadesResult, ResumenHoyResult } from "@/lib/api-types";
import { NovedadesBanner } from "./novedades-banner";
import { useFiltrosIgnorados } from "./alcance";
import { AvisoAlcance } from "./aviso-alcance";

/**
 * Mercado abierto — los cuatro contadores que exigen mirar hoy.
 *
 * Tres cosas cambian respecto a la versión anterior, y las tres son la misma
 * cosa: que la tarjeta no prometa lo que el enlace no cumple.
 *
 * 1. **El enlace arrastra el ámbito.** Iba con `href="/detalle?…"` a secas, así
 *    que con un chip de CCAA activo la tarjeta contaba Madrid y abría España.
 *    Ahora pasa por `useScopedHref`, que fusiona ámbito y recorte propio.
 * 2. **El destino dice si es exacto.** La cabecera afirmaba que «cada tarjeta
 *    abre su listado ya filtrado» y dos de las cuatro abrían `/detalle` sin
 *    filtro ninguno: «Vencen 48h: 37» llevaba a un listado de 148.000. El
 *    backend no tiene filtro por fecha de cierre ni por el P75 de importe
 *    (`GET /licitaciones` no los acepta), y fabricarlo en cliente sería
 *    inventar el filtrado (ADR-014). Así que el pie de la tarjeta marca con `≈`
 *    los dos destinos que se quedan cortos y dice en qué.
 * 3. **El alcance del endpoint se declara.** `/analytics/resumen/hoy` sólo
 *    aplica fecha, CCAA y tecnología; con búsqueda o estado en el ámbito, estos
 *    contadores miden otro conjunto que la tira de contexto de abajo. Ver
 *    `alcance.ts`.
 */

const ACCENT = {
  hot: "var(--score-hot)",
  warm: "var(--score-warm)",
  cold: "var(--score-cold)",
  primary: "var(--primary)",
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
  alert?: boolean;
}

function UrgentCard({ card, loading }: { card: Tarjeta; loading: boolean }) {
  const scopedHref = useScopedHref();
  const color = `hsl(${ACCENT[card.accent]})`;
  const Icon = card.icon;

  return (
    <Link
      href={scopedHref(card.href)}
      className={cn(
        "group bg-card/70 flex min-h-[118px] flex-col rounded-xl border px-3.5 py-3 text-left",
        "hover:border-primary/45 transition-[transform,border-color] duration-140 ease-out hover:-translate-y-px",
        card.alert ? "border-destructive/50" : "border-border/60",
      )}
    >
      <div className="mb-3 flex items-center gap-2.5">
        <span
          className="grid h-6 w-6 flex-none place-items-center rounded-md"
          style={{ background: `hsl(${ACCENT[card.accent]} / 0.14)`, color }}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="text-[11.5px] font-semibold">{card.title}</span>
      </div>
      {loading ? (
        <Skeleton className="h-8 w-20 rounded" />
      ) : (
        <div className="tf-tnum font-mono text-[30px] leading-none font-semibold" style={{ color }}>
          {formatNumber(card.value)}
        </div>
      )}
      <div className="text-muted-foreground mt-1.5 text-[11px] leading-[1.45]">{card.subtitle}</div>
      <div className="border-border/40 mt-auto flex items-center gap-1.5 border-t pt-2.5">
        <span
          className={cn(
            "min-w-0 flex-1 truncate font-mono text-[10.5px]",
            card.exacto ? "text-muted-foreground" : "text-[hsl(var(--warning))]",
          )}
        >
          {card.exacto ? card.target : `≈ ${card.target}`}
        </span>
        <ArrowRight
          className="text-primary h-3 w-3 flex-none transition-transform duration-140 ease-out group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </div>
    </Link>
  );
}

export function AtencionCards() {
  const ignorados = useFiltrosIgnorados();

  const novedades = useFilteredQuery<ResumenNovedadesResult>(
    ["analytics", "resumen", "novedades"],
    "/api/v1/analytics/resumen/novedades",
    { staleTime: 5 * 60 * 1000 },
  );

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

  const data = hoy.data;

  // El recuento es el dato central de la pantalla y saltaba en silencio para
  // quien usa lector (hallazgo 5 de la auditoría UX).
  useAnnounceOnChange(
    data
      ? `Mercado abierto: ${data.vencen_48h} vencen en 48 horas, ${data.nuevas_24h} nuevas en 24 horas, ${data.total_activas} activas.`
      : null,
  );

  const cards: Tarjeta[] = [
    {
      key: "vencen",
      title: "Vencen 48h",
      value: data?.vencen_48h,
      subtitle: "Cierran en menos de 2 días",
      icon: Clock,
      accent: "hot",
      href: "/detalle",
      target: "/detalle · sin filtro de cierre",
      exacto: false,
      alert: Boolean(data && data.vencen_48h > 0),
    },
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
      href: "/detalle?solo_abiertas=true",
      target: "/detalle abiertas · sin el corte P75",
      exacto: false,
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
    {
      key: "activas",
      title: "Total activas",
      value: data?.total_activas,
      subtitle: "Sin adjudicar ni cerrar",
      icon: Activity,
      accent: "primary",
      href: "/detalle?solo_abiertas=true",
      target: "/detalle sólo abiertas",
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

      <NovedadesBanner data={novedades.data} isLoading={novedades.isLoading} />

      <AvisoAlcance ignorados={ignorados} />

      {hoy.error ? (
        <PanelError
          title="No se pudo cargar el estado de hoy"
          detail={(hoy.error as Error).message}
          onRetry={() => void hoy.refetch()}
        />
      ) : (
        <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {cards.map((card) => (
            <Stagger.Item key={card.key}>
              <UrgentCard card={card} loading={hoy.isLoading} />
            </Stagger.Item>
          ))}
        </Stagger>
      )}
    </section>
  );
}
