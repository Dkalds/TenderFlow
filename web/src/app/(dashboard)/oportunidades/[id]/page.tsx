"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CalendarClock, ExternalLink, Landmark } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SkeletonCard } from "@/components/ui/skeleton";
import { PursuitEditor } from "@/components/pursuits/pursuit-editor";
import { PriceScenariosPanel } from "@/components/pursuits/price-scenarios";
import { PursuitDecisionBadge, PursuitOutcomeBadge, PursuitStatusBadge, daysUntil, formatDate } from "@/components/pursuits/pursuit-presenters";
import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";
import { usePursuit } from "@/hooks/use-pursuits";

export default function OpportunityDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: pursuit, isLoading, error } = usePursuit(params.id ?? null);

  if (isLoading) return <div className="space-y-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>;
  if (error || !pursuit) return <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-5 text-sm text-destructive">No se pudo abrir esta oportunidad. {error instanceof Error ? error.message : "No encontrada"}</div>;

  const deadline = daysUntil(pursuit.tender_deadline);
  return (
    <div className="space-y-5">
      <Link href="/oportunidades" className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />Volver a oportunidades</Link>
      <section className="tf-card-shadow relative overflow-hidden rounded-xl border border-border bg-card/80 p-5 sm:p-7"><div aria-hidden="true" className="absolute right-0 top-0 h-full w-1/3 bg-gradient-to-l from-primary/10 to-transparent" /><div className="relative"><div className="flex flex-wrap gap-2"><PursuitStatusBadge status={pursuit.status} /><PursuitDecisionBadge decision={pursuit.decision} /><PursuitOutcomeBadge outcome={pursuit.outcome} /></div><h1 className="tf-display mt-4 max-w-4xl">{pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}</h1><div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground"><span className="inline-flex items-center gap-1.5"><Landmark className="h-4 w-4" />Referencia {pursuit.licitacion_id}</span><span className="inline-flex items-center gap-1.5"><CalendarClock className="h-4 w-4" />{deadline ?? formatDate(pursuit.tender_deadline)}</span></div><Link href={`/detalle?lic=${encodeURIComponent(pursuit.licitacion_id)}`} className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">Ver anuncio original <ExternalLink className="h-3.5 w-3.5" /></Link></div></section>
      <TenderFactSheetPanel licitacionId={pursuit.licitacion_id} />
      <PriceScenariosPanel licitacionId={pursuit.licitacion_id} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_19rem]"><PursuitEditor pursuit={pursuit} /><aside className="space-y-4"><Card><CardHeader><CardTitle className="text-sm">Contexto de la licitación</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><div><p className="text-xs text-muted-foreground">Fecha límite</p><p className="font-semibold">{formatDate(pursuit.tender_deadline)}</p></div><div><p className="text-xs text-muted-foreground">Responsable actual</p><p className="font-semibold">{pursuit.responsible_name ?? "Sin asignar"}</p></div><div><p className="text-xs text-muted-foreground">Última actualización</p><p className="font-semibold">{formatDate(pursuit.updated_at)}</p></div></CardContent></Card><p className="px-1 text-xs leading-relaxed text-muted-foreground">Los escenarios se basan en el universo observado. La decisión y el precio final siguen siendo responsabilidad del equipo.</p></aside></div>
    </div>
  );
}
