"use client";

import { useQuery } from "@tanstack/react-query";
import { PanelError, SectionTitle } from "@/components/console/panel";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { radarKeys } from "@/lib/query-keys";
import { Skeleton } from "@/components/ui/skeleton";

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
  const { data, isLoading, error, refetch } = useQuery<OrganoDetailResult>({
    queryKey: radarKeys.organo(organo),
    queryFn: () =>
      fetchWithAuth<OrganoDetailResult>(
        `/api/v1/analytics/organos/${encodeURIComponent(organo!)}`,
      ),
    enabled: Boolean(organo),
    staleTime: 5 * 60_000,
    // El fallo se dice en el bloque: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  if (!organo) return null;

  // Denominador, nunca se pinta: el `total > 0` de abajo convierte la ausencia
  // en `share = null`, que es lo correcto.
  const total = data?.kpis?.importe_total ?? 0; // fdi-allow:nulo-a-cero
  const rivals = (data?.top_adjudicatarios ?? []).slice(0, 3);

  return (
    <>
      <SectionTitle as="h3" hint="histórico del órgano">
        Competencia esperada
      </SectionTitle>
      <div className="flex flex-col gap-1.5 pb-5">
        {isLoading ? (
          <>
            <Skeleton className="h-9 rounded-md" />
            <Skeleton className="h-9 rounded-md" />
            <Skeleton className="h-9 rounded-md" />
          </>
        ) : error ? (
          // Sin esto, un fallo se leía «Sin adjudicaciones registradas»: un
          // vacío falso sobre justo el dato que se vino a mirar.
          <PanelError
            variant="inline"
            title="No se pudo cargar el histórico del órgano"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : rivals.length === 0 ? (
          <p className="text-tf-meta text-muted-foreground">
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
                {/* Avatar neutro: el naranja queda para acción y selección. */}
                <span
                  className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-border/70 bg-secondary text-tf-micro font-semibold text-muted-foreground"
                  aria-hidden="true"
                >
                  {initials}
                </span>
                <span className="min-w-0 flex-1 truncate text-tf-meta">{rival.nombre}</span>
                <span className="tf-tnum shrink-0 text-tf-micro text-muted-foreground">
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
