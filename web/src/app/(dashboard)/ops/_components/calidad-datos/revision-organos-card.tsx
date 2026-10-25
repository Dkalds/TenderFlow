"use client";

/**
 * Cola de órganos por decidir (ADR-032 §C): grafías de un órgano de
 * contratación que se parecen a uno ya conocido, pero no lo bastante para
 * juntarlas sin que lo mire alguien.
 *
 * Juntar dos organismos distintos —los «Servicio de Salud» de dos
 * comunidades— mezcla dos historiales de contratación, y ese error no se ve en
 * la ficha. Por eso la decisión es de una persona:
 *
 * - **Es el mismo**: la grafía pasa a ser otro nombre del órgano conocido.
 * - **Es otro órgano**: queda como órgano propio.
 *
 * En los dos casos las licitaciones que esperaban con esa grafía reciben su
 * órgano, y el aviso dice cuántas. Mismo patrón que `revision-duplicados-card`.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle, ROTULO_DATO } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys, analyticsKeys } from "@/lib/query-keys";
import { formatNumber, formatPercent } from "@/lib/utils";

type Listado = Schemas["OrganosPendientes"];
type Pendiente = Schemas["OrganoPendiente"];
type Resuelto = Schemas["OrganoResuelto"];
type Decision = "fusionar" | "separar";

const ETIQUETA: Record<Decision, { pedir: string; confirmar: string }> = {
  fusionar: { pedir: "Es el mismo", confirmar: "Sí, juntarlos" },
  separar: { pedir: "Es otro órgano", confirmar: "Sí, separarlo" },
};

export function RevisionOrganosCard() {
  const [confirmando, setConfirmando] = useState<{ id: number; decision: Decision } | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<Listado>({
    queryKey: adminKeys.revision.organos,
    queryFn: () =>
      apiGet("/api/v1/admin/revision/organos", { params: { query: { limit: 50 } } }) as Promise<Listado>,
    meta: META_ERROR_EN_LINEA,
  });

  const resolver = useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: Decision }) =>
      apiMutate<Resuelto>("POST", `/api/v1/admin/revision/organos/${id}/resolver`, {
        aceptar: decision === "fusionar",
      }),
    onSuccess: (res) => {
      toast.success(res.detalle);
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.organos });
      void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
    },
    meta: { errorTitle: "No se pudo resolver la revisión" },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.organos });
    },
    onSettled: () => setConfirmando(null),
  });

  const items: Pendiente[] = data?.items ?? [];
  const sinPermiso = error instanceof ApiError && error.status === 403;

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Órganos por decidir"
        actions={
          data?.total != null ? (
            <Badge variant={data.total > 0 ? "warning" : "neutral"} size="sm">
              {formatNumber(data.total)} pendientes
            </Badge>
          ) : null
        }
      />
      <p className="mb-3 max-w-prose text-tf-meta text-muted-foreground">
        Nombres de órgano que se parecen a uno conocido. Hasta que se decide, sus licitaciones se quedan sin órgano
        asignado.
      </p>
      {sinPermiso ? (
        <Aviso tone="info">Sólo los administradores pueden revisar los órganos.</Aviso>
      ) : error ? (
        <PanelError variant="inline" title="No se pudo cargar la cola" error={error} onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : items.length === 0 ? (
        <PanelEmpty size="sm" title="No hay nada pendiente" hint="Ningún nombre de órgano espera una decisión." />
      ) : (
        <ul className="divide-y divide-divider rounded-md border border-divider" aria-label="Órganos por decidir">
          {items.map((item) => {
            const armada = confirmando?.id === item.id ? confirmando.decision : null;
            const boton = (decision: Decision) => {
              const pidiendo = armada === decision;
              return (
                <Button
                  size="sm"
                  variant={pidiendo ? "destructive" : decision === "fusionar" ? "outline" : "ghost"}
                  disabled={resolver.isPending}
                  aria-label={
                    pidiendo
                      ? `Confirmar: ${ETIQUETA[decision].pedir.toLowerCase()} (${item.nombre_original})`
                      : `${ETIQUETA[decision].pedir}: ${item.nombre_original}`
                  }
                  onClick={() => {
                    if (!pidiendo) {
                      setConfirmando({ id: item.id, decision });
                      return;
                    }
                    resolver.mutate({ id: item.id, decision });
                  }}
                >
                  {pidiendo ? ETIQUETA[decision].confirmar : ETIQUETA[decision].pedir}
                </Button>
              );
            };
            return (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2">
                  <div className="min-w-0">
                    <p className={ROTULO_DATO}>Nombre recibido</p>
                    <p className="text-tf-body font-medium">{item.nombre_original}</p>
                    {item.dir3 ? <p className="font-mono text-tf-meta text-muted-foreground">{item.dir3}</p> : null}
                  </div>
                  <div className="min-w-0">
                    <p className={ROTULO_DATO}>Se parece a</p>
                    <p className="text-tf-body font-medium">{item.candidato_nombre ?? "Sin candidato"}</p>
                    <p className="text-tf-meta text-muted-foreground">
                      Parecido {formatPercent((item.score ?? 0) * 100, 0)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {armada && <span className="text-tf-meta text-warning">¿Confirmar?</span>}
                  {armada !== "separar" && item.candidato_organo_id != null && boton("fusionar")}
                  {armada !== "fusionar" && boton("separar")}
                  {armada && (
                    <Button size="sm" variant="ghost" onClick={() => setConfirmando(null)}>
                      Cancelar
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
