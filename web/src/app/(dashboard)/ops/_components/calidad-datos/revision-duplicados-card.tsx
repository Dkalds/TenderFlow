"use client";

/**
 * Cola de duplicados por decidir (ADR-026): pares que el detector sospecha que
 * son el mismo contrato publicado dos veces pero no puede confirmar solo.
 *
 * Mientras un par está pendiente, la fila sospechosa no sale en los listados
 * pero sí cuenta en cuotas e importes. Decidir lo cierra en un sentido o en
 * otro:
 *
 * - **Es el mismo**: la fila sale también de las métricas. Su ficha sigue
 *   respondiendo, con el aviso de a cuál duplica.
 * - **No es el mismo**: vuelve a los listados y sigue contando.
 *
 * Patrón de `ejecuciones/dlq-card.tsx`: una sola confirmación armada a la vez,
 * un único toast por decisión y el «sin permisos» dicho en el panel. Sólo
 * administradores.
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
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

type Listado = Schemas["DuplicadosPendientes"];
type Par = Schemas["DuplicadoPendiente"];
type Resuelto = Schemas["DuplicadoResuelto"];
type Decision = "mismo" | "distinto";

const ETIQUETA: Record<Decision, { pedir: string; confirmar: string }> = {
  mismo: { pedir: "Es el mismo", confirmar: "Sí, es el mismo" },
  distinto: { pedir: "No es el mismo", confirmar: "Sí, son distintos" },
};

function Lado({
  rotulo,
  id,
  titulo,
  fuente,
  organo,
  fecha,
  importe,
}: {
  rotulo: string;
  id: string;
  titulo?: string | null;
  fuente?: string | null;
  organo?: string | null;
  fecha?: string | null;
  importe?: number | null;
}) {
  return (
    <div className="min-w-0 space-y-0.5">
      <p className={ROTULO_DATO}>{rotulo}</p>
      <p className="text-tf-body font-medium">{titulo ?? "Sin título"}</p>
      <p className="truncate text-tf-meta text-muted-foreground">{organo ?? "Órgano sin informar"}</p>
      <p className="text-tf-meta text-muted-foreground">
        <span className="font-mono">{id}</span> · {fuente ?? "fuente desconocida"} · {formatDate(fecha)} ·{" "}
        {formatCurrency(importe)}
      </p>
    </div>
  );
}

export function RevisionDuplicadosCard() {
  // Una sola confirmación armada a la vez, entre todas las filas y las dos
  // decisiones: con dos, un segundo clic distraído ejecuta la que no se miraba.
  const [confirmando, setConfirmando] = useState<{ id: string; decision: Decision } | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<Listado>({
    queryKey: adminKeys.revision.duplicados,
    queryFn: () =>
      apiGet("/api/v1/admin/revision/duplicados", { params: { query: { limit: 50 } } }) as Promise<Listado>,
    meta: META_ERROR_EN_LINEA,
  });

  const resolver = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: Decision }) =>
      apiMutate<Resuelto>(
        "POST",
        `/api/v1/admin/revision/duplicados/${encodeURIComponent(id)}/resolver`,
        { aceptar: decision === "mismo" },
      ),
    onSuccess: (res) => {
      toast.success(res.detalle);
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.duplicados });
      void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
    },
    meta: { errorTitle: "No se pudo resolver el par" },
    onError: () => {
      // Un 404 es que otra persona ya lo decidió: la lista tiene que ponerse al día.
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.duplicados });
    },
    onSettled: () => setConfirmando(null),
  });

  const items: Par[] = data?.items ?? [];
  const sinPermiso = error instanceof ApiError && error.status === 403;

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Duplicados por decidir"
        actions={
          data?.total != null ? (
            <Badge variant={data.total > 0 ? "warning" : "neutral"} size="sm">
              {formatNumber(data.total)} pendientes
            </Badge>
          ) : null
        }
      />
      <p className="mb-3 max-w-prose text-tf-meta text-muted-foreground">
        Pares que parecen el mismo contrato publicado dos veces. Mientras no se decide, el segundo no sale en los
        listados pero sigue contando en cuotas e importes.
      </p>
      {sinPermiso ? (
        <Aviso tone="info">Sólo los administradores pueden revisar los duplicados.</Aviso>
      ) : error ? (
        <PanelError variant="inline" title="No se pudo cargar la cola" error={error} onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : items.length === 0 ? (
        <PanelEmpty size="sm" title="No hay nada pendiente" hint="Ningún par espera una decisión." />
      ) : (
        <ul className="divide-y divide-divider rounded-md border border-divider" aria-label="Pares por decidir">
          {items.map((par) => {
            const armada = confirmando?.id === par.licitacion_id ? confirmando.decision : null;
            const boton = (decision: Decision) => {
              const pidiendo = armada === decision;
              return (
                <Button
                  size="sm"
                  variant={pidiendo ? "destructive" : decision === "mismo" ? "outline" : "ghost"}
                  disabled={resolver.isPending}
                  aria-label={
                    pidiendo
                      ? `Confirmar: ${ETIQUETA[decision].pedir.toLowerCase()} (${par.licitacion_id})`
                      : `${ETIQUETA[decision].pedir}: ${par.licitacion_id}`
                  }
                  onClick={() => {
                    if (!pidiendo) {
                      setConfirmando({ id: par.licitacion_id, decision });
                      return;
                    }
                    resolver.mutate({ id: par.licitacion_id, decision });
                  }}
                >
                  {pidiendo ? ETIQUETA[decision].confirmar : ETIQUETA[decision].pedir}
                </Button>
              );
            };
            return (
              <li key={par.licitacion_id} className="space-y-3 p-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Lado
                    rotulo="Se queda"
                    id={par.canonical_id}
                    titulo={par.titulo_canonica}
                    fuente={par.fuente_canonica}
                    organo={par.organo_canonica}
                    fecha={par.fecha_publicacion_canonica}
                    importe={par.importe_canonica}
                  />
                  <Lado
                    rotulo="Posible duplicado"
                    id={par.licitacion_id}
                    titulo={par.titulo}
                    fuente={par.fuente}
                    organo={par.organo}
                    fecha={par.fecha_publicacion}
                    importe={par.importe}
                  />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-tf-meta text-muted-foreground">
                    Confianza {formatPercent(par.confianza * 100, 0)}
                  </span>
                  <div className="flex items-center gap-2">
                    {armada && <span className="text-tf-meta text-warning">¿Confirmar?</span>}
                    {armada !== "distinto" && boton("mismo")}
                    {armada !== "mismo" && boton("distinto")}
                    {armada && (
                      <Button size="sm" variant="ghost" onClick={() => setConfirmando(null)}>
                        Cancelar
                      </Button>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
