"use client";

import * as React from "react";
import { BriefcaseBusiness, CircleCheckBig, CircleX, Clock3, Search, Trophy } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SkeletonCard } from "@/components/ui/skeleton";
import { PursuitCard } from "@/components/pursuits/pursuit-card";
import { formatEur } from "@/components/pursuits/pursuit-presenters";
import { type PursuitStatus, usePursuitMetrics, usePursuits } from "@/hooks/use-pursuits";

const lanes: Array<{ title: string; statuses: PursuitStatus[]; description: string }> = [
  { title: "Por decidir", statuses: ["identified", "qualifying", "go_no_go"], description: "Identificadas, cualificando o en GO/NO-GO" },
  { title: "En preparación", statuses: ["preparing"], description: "Trabajo activo de la oferta" },
  { title: "Presentadas", statuses: ["submitted"], description: "Pendientes de resultado" },
  { title: "Cerradas", statuses: ["won", "lost", "withdrawn"], description: "Ganadas, perdidas o retiradas" },
];

export default function OportunidadesPage() {
  const [query, setQuery] = React.useState("");
  const pursuits = usePursuits();
  const metrics = usePursuitMetrics();
  const items = (pursuits.data?.items ?? []).filter((pursuit) =>
    !query.trim() || `${pursuit.tender_title ?? ""} ${pursuit.licitacion_id} ${pursuit.responsible_name ?? ""}`.toLocaleLowerCase("es").includes(query.trim().toLocaleLowerCase("es")),
  );

  return (
    <div className="space-y-5">
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card/75 p-5 sm:flex-row sm:items-end sm:justify-between sm:p-7">
        <div><div className="mb-3 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary"><BriefcaseBusiness className="h-3.5 w-3.5" />Espacio de ejecución</div><h1 className="tf-display">Oportunidades del equipo</h1><p className="mt-2 max-w-2xl text-muted-foreground">Convierte señales en decisiones trazables, responsables claros y resultados medibles.</p></div>
        <label className="relative block w-full sm:max-w-xs" htmlFor="pursuit-search"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><Input id="pursuit-search" className="pl-9" placeholder="Buscar oportunidad" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      </section>

      <section aria-label="Resumen de oportunidades" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={Clock3} label="Identificadas" value={metrics.data?.pursuits_identified} />
        <Metric icon={CircleCheckBig} label="Presentadas" value={metrics.data?.pursuits_submitted} />
        <Metric icon={Trophy} label="Ganadas" value={metrics.data?.pursuits_won} />
        <Metric icon={CircleX} label="Adjudicado" value={metrics.data ? formatEur(metrics.data.awarded_amount_eur) : undefined} />
      </section>

      {pursuits.error ? <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-5 text-sm text-destructive">No se pudieron cargar las oportunidades. {(pursuits.error as Error).message}</div> : <section className="grid gap-5 xl:grid-cols-4">{lanes.map((lane) => { const laneItems = items.filter((item) => lane.statuses.includes(item.status)); return <div key={lane.title}><div className="mb-3 flex items-baseline justify-between"><div><h2 className="tf-h2">{lane.title}</h2><p className="text-xs text-muted-foreground">{lane.description}</p></div><span className="text-sm font-semibold text-muted-foreground">{laneItems.length}</span></div><div className="space-y-3">{pursuits.isLoading ? <><SkeletonCard /><SkeletonCard /></> : laneItems.length ? laneItems.map((pursuit) => <PursuitCard key={pursuit.id} pursuit={pursuit} />) : <Card className="border-dashed shadow-none"><CardContent className="py-8 text-center text-sm text-muted-foreground">Sin oportunidades en esta fase.</CardContent></Card>}</div></div>; })}</section>}
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Clock3; label: string; value: string | number | undefined }) {
  return <Card><CardContent className="flex items-center gap-3 p-4"><span className="rounded-lg bg-primary/10 p-2 text-primary"><Icon className="h-4 w-4" /></span><div><p className="text-xs text-muted-foreground">{label}</p><p className="tf-kpi mt-0.5">{value ?? "—"}</p></div></CardContent></Card>;
}
