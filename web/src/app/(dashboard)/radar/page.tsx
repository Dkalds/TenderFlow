"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Building2, CalendarClock, CircleSlash2, Eye, Loader2, RadioTower, Star } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton";
import { formatDate, formatEur, daysUntil } from "@/components/pursuits/pursuit-presenters";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import { useAddWatchlistItem, useWatchlistItems } from "@/hooks/use-watchlist-items";
import { type RadarTender, useRadar } from "@/hooks/use-radar";
import { PageHeader } from "@/components/layout/page-header";

function scoreCopy(tender: RadarTender): string {
  if (tender.band) return tender.band;
  if (tender.score != null) return `Score ${Math.round(tender.score)}`;
  return "Sin puntuar";
}

function RadarItem({
  tender,
  ranking,
  onDismiss,
}: {
  tender: RadarTender;
  ranking: boolean;
  onDismiss: (tender: RadarTender) => void;
}) {
  const router = useRouter();
  const createPursuit = useCreatePursuit();
  const addWatchlist = useAddWatchlistItem();
  const { data: watched = [] } = useWatchlistItems();
  const watchedAlready = watched.some((item) => item.id_externo === tender.id_externo);
  const deadline = daysUntil(tender.fecha_limite);

  const openPursuit = async () => {
    try {
      const pursuit = await createPursuit.mutateAsync({ licitacion_id: tender.id_externo });
      toast.success("Oportunidad abierta para el equipo");
      router.push(`/oportunidades/${pursuit.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo abrir la oportunidad");
    }
  };

  const follow = async () => {
    if (watchedAlready) return;
    try {
      await addWatchlist.mutateAsync(tender.id_externo);
      toast.success("Licitación añadida a seguimiento");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo seguir la licitación");
    }
  };

  return (
    <Card className="group relative overflow-hidden">
      <CardContent className="p-0">
        <div className="absolute inset-y-0 left-0 w-1 bg-primary" aria-hidden="true" />
        <div className="p-5 pl-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-primary">
                {/* Mientras el scoring está en vuelo el badge es un skeleton, no
                    un texto: "Sin puntuar" antes de tiempo se lee como una
                    categoría del dato, no como "todavía no lo sé". */}
                {ranking ? (
                  <Skeleton className="h-5 w-20 rounded-full" />
                ) : (
                  <span className="rounded-full bg-primary/10 px-2 py-0.5">{scoreCopy(tender)}</span>
                )}
                {tender.tecnologia && <span className="text-muted-foreground">{tender.tecnologia}</span>}
              </div>
              <h2 className="mt-2 text-base font-semibold leading-snug">{tender.titulo ?? `Licitación ${tender.id_externo}`}</h2>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5" />{tender.organo_contratacion ?? "Órgano no informado"}</span>
                <span className="inline-flex items-center gap-1.5"><CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />{deadline ?? formatDate(tender.fecha_limite)}</span>
                <span className="font-medium text-foreground">{formatEur(tender.importe)}</span>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => onDismiss(tender)} aria-label={`Descartar ${tender.titulo ?? tender.id_externo}`}><CircleSlash2 />Descartar</Button>
              <Button variant="outline" size="sm" onClick={() => void follow()} disabled={watchedAlready || addWatchlist.isPending}><Star className={watchedAlready ? "fill-primary text-primary" : ""} />{watchedAlready ? "Siguiendo" : "Seguir"}</Button>
              <Button size="sm" onClick={() => void openPursuit()} disabled={createPursuit.isPending}>{createPursuit.isPending ? <Loader2 className="animate-spin" /> : <ArrowUpRight />}Abrir oportunidad</Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function RadarPage() {
  const { data, isLoading, isRanking, error } = useRadar();
  const [dismissed, setDismissed] = React.useState<Set<string>>(() => new Set());
  const tenders = (data?.items ?? []).filter((item) => !dismissed.has(item.id_externo));

  const restore = React.useCallback((id: string) => {
    setDismissed((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }, []);

  // El descarte vive sólo en memoria: no hay endpoint de dismiss en el backend,
  // así que no persiste entre recargas (ver P1 en docs/IMPROVEMENT_BACKLOG.md).
  // Mientras sea así, la acción se acompaña de un undo inmediato y el copy lo
  // dice — mejor que un descarte silencioso que el usuario cree definitivo.
  const dismiss = React.useCallback(
    (tender: RadarTender) => {
      setDismissed((current) => new Set(current).add(tender.id_externo));
      toast("Señal descartada en esta sesión", {
        description: tender.titulo ?? tender.id_externo,
        action: { label: "Deshacer", onClick: () => restore(tender.id_externo) },
      });
    },
    [restore],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        variant="hero"
        eyebrow="Radar de oportunidades"
        eyebrowIcon={RadioTower}
        title="Qué merece atención ahora."
        description="Señales recientes del mercado para decidir qué seguir y qué convertir en una oportunidad de equipo."
        actions={
          <Link
            href="/oportunidades"
            className="inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline"
          >
            <Eye className="h-4 w-4" aria-hidden="true" />
            Ver oportunidades abiertas
          </Link>
        }
      />

      {/* El alcance se declara, no se insinúa: la lista son las 24 licitaciones
          más recientes reordenadas por afinidad, no el top-24 por score de todo
          el corpus. Ver la nota de alcance en `hooks/use-radar.ts`. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {isLoading
            ? "Actualizando señales…"
            : isRanking
              ? "Ordenando por afinidad…"
              : `${tenders.length} señales recientes, ordenadas por afinidad`}
        </p>
        {dismissed.size > 0 && (
          <Button variant="link" size="sm" onClick={() => setDismissed(new Set())}>
            Restaurar {dismissed.size} descartada{dismissed.size === 1 ? "" : "s"}
          </Button>
        )}
      </div>

      {error ? <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-5 text-sm text-destructive">No se pudo cargar el radar. {(error as Error).message}</div> : isLoading ? <div className="grid gap-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div> : tenders.length === 0 ? <EmptyState icon={RadioTower} title="Radar al día" hint="No quedan señales con los criterios actuales." /> : <div className="grid gap-4">{tenders.map((tender) => <RadarItem key={tender.id_externo} tender={tender} ranking={isRanking} onDismiss={dismiss} />)}</div>}
    </div>
  );
}
