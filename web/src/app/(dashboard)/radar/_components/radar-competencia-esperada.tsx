"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { radarKeys } from "@/lib/query-keys";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionTitle } from "./radar-inspector-piezas";

interface TopAdjudicatario {
  nombre: string;
  count: number;
  importe: number;
}

interface OrganoDetailResult {
  kpis?: { importe_total?: number };
  top_adjudicatarios?: TopAdjudicatario[];
}

/** Adjudicatarios habituales del órgano — la competencia que cabe esperar. */
export function ExpectedCompetition({ organo }: { organo: string | null | undefined }) {
  const { data, isLoading } = useQuery<OrganoDetailResult>({
    queryKey: radarKeys.organo(organo),
    queryFn: () =>
      fetchWithAuth<OrganoDetailResult>(
        `/api/v1/analytics/organos/${encodeURIComponent(organo!)}`,
      ),
    enabled: Boolean(organo),
    staleTime: 5 * 60_000,
  });

  if (!organo) return null;

  // Denominador, nunca se pinta: el `total > 0` de abajo convierte la ausencia
  // en `share = null`, que es lo correcto.
  const total = data?.kpis?.importe_total ?? 0; // fdi-allow:nulo-a-cero
  const rivals = (data?.top_adjudicatarios ?? []).slice(0, 3);

  return (
    <>
      <SectionTitle
        aside={
          <span className="text-[10.5px] text-muted-foreground/70">histórico del órgano</span>
        }
      >
        Competencia esperada
      </SectionTitle>
      <div className="flex flex-col gap-1.5 pb-5">
        {isLoading ? (
          <>
            <Skeleton className="h-9 rounded-md" />
            <Skeleton className="h-9 rounded-md" />
            <Skeleton className="h-9 rounded-md" />
          </>
        ) : rivals.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Sin adjudicaciones registradas para este órgano.
          </p>
        ) : (
          rivals.map((rival) => {
            const initials = rival.nombre
              .split(/[\s/]+/)
              .slice(0, 2)
              .map((word) => word[0] ?? "")
              .join("");
            const share = total > 0 ? Math.round((rival.importe / total) * 100) : null;
            return (
              <div
                key={rival.nombre}
                className="flex items-center gap-2.5 rounded-md border border-border/60 bg-card px-2.5 py-2"
              >
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded border border-primary/25 bg-primary/12 font-mono text-[9px] font-semibold text-primary">
                  {initials}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs">{rival.nombre}</span>
                <span className="tf-tnum shrink-0 font-mono text-[11px] text-muted-foreground">
                  {share != null ? `${share}%` : `${rival.count} adj.`}
                </span>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}
