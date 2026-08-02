"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CalendarClock, ExternalLink, Landmark, User } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { PursuitEditor } from "@/components/pursuits/pursuit-editor";
import { PriceScenariosPanel } from "@/components/pursuits/price-scenarios";
import {
  PursuitDecisionBadge,
  PursuitOutcomeBadge,
  PursuitStatusBadge,
  daysUntil,
  formatDate,
} from "@/components/pursuits/pursuit-presenters";
import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";
import { Panel, PanelError, PanelTabs, SectionTitle } from "@/components/console/panel";
import { usePursuit } from "@/hooks/use-pursuits";

/**
 * Ficha de la oportunidad — Decisión primero.
 *
 * Eran seis paneles apilados con el formulario de decisión **al final**, detrás
 * de la ficha del pliego y de los escenarios de precio: lo único que el usuario
 * abre la ficha para tocar quedaba a tres pantallas de scroll. Ahora son tres
 * pestañas y Decisión abre; Pliego y Precio quedan a un clic.
 *
 * No se ha quitado nada: el editor completo, la ficha del pliego y los
 * escenarios siguen siendo los mismos componentes, con su `expected_version` y
 * su bloqueo de P(ganar) intactos.
 */

type TabKey = "decision" | "pliego" | "precio";

export default function OpportunityDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: pursuit, isLoading, error, refetch } = usePursuit(params.id ?? null);
  const [tab, setTab] = React.useState<TabKey>("decision");

  if (isLoading) {
    return (
      <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col gap-3 p-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-[360px] w-full rounded-xl" />
      </div>
    );
  }

  if (error || !pursuit) {
    return (
      <div className="grid h-[calc(100vh-52px)] place-items-center p-10">
        <PanelError
          title="No se pudo abrir esta oportunidad"
          detail={error instanceof Error ? error.message : "No encontrada"}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  const deadline = daysUntil(pursuit.tender_deadline);

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
      <header className="flex-none border-b border-border/60 bg-card/40 px-4 pt-3.5">
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <PursuitStatusBadge status={pursuit.status} />
          <PursuitDecisionBadge decision={pursuit.decision} />
          <PursuitOutcomeBadge outcome={pursuit.outcome} />
          <div className="flex-1" />
          <span className="text-[11px] text-muted-foreground">
            Última actualización {formatDate(pursuit.updated_at)}
          </span>
        </div>

        <h1 className="mb-2.5 max-w-[74ch] font-display text-[19px] font-semibold leading-[1.28] tracking-[-0.015em] text-pretty">
          {pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}
        </h1>

        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Landmark className="h-3.5 w-3.5" aria-hidden="true" />
            Referencia{" "}
            <span className="font-mono text-[11.5px] text-foreground/80">
              {pursuit.licitacion_id}
            </span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
            {deadline ?? formatDate(pursuit.tender_deadline)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <User className="h-3.5 w-3.5" aria-hidden="true" />
            Responsable{" "}
            <span className="font-medium text-foreground">
              {pursuit.responsible_name ?? "Sin asignar"}
            </span>
          </span>
          <div className="flex-1" />
          <Link
            href={`/detalle?lic=${encodeURIComponent(pursuit.licitacion_id)}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium"
          >
            Ver anuncio original <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </Link>
          <Link
            href="/oportunidades"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3 w-3" aria-hidden="true" />
            Oportunidades
          </Link>
        </div>

        <PanelTabs
          label="Secciones de la oportunidad"
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "decision", label: "Decisión" },
            { key: "pliego", label: "Pliego" },
            { key: "precio", label: "Precio" },
          ]}
        />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-8 pt-4">
        {tab === "decision" && (
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <PursuitEditor pursuit={pursuit} />
            <aside className="flex flex-col gap-3.5">
              <Panel>
                <SectionTitle>Contexto de la licitación</SectionTitle>
                <dl className="space-y-2.5 text-xs">
                  <div>
                    <dt className="text-[10.5px] text-muted-foreground">Fecha límite</dt>
                    <dd className="font-semibold">{formatDate(pursuit.tender_deadline)}</dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] text-muted-foreground">Responsable actual</dt>
                    <dd className="font-semibold">
                      {pursuit.responsible_name ?? "Sin asignar"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] text-muted-foreground">Última actualización</dt>
                    <dd className="font-semibold">{formatDate(pursuit.updated_at)}</dd>
                  </div>
                </dl>
              </Panel>
              <p className="px-1 text-[11px] leading-relaxed text-muted-foreground">
                Los escenarios se basan en el universo observado. La decisión y el precio final
                siguen siendo responsabilidad del equipo.
              </p>
            </aside>
          </div>
        )}

        {tab === "pliego" && <TenderFactSheetPanel licitacionId={pursuit.licitacion_id} />}
        {tab === "precio" && <PriceScenariosPanel licitacionId={pursuit.licitacion_id} />}
      </div>
    </div>
  );
}
