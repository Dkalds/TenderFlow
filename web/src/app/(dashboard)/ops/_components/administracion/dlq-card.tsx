"use client";

/**
 * Cola de errores (Dead Letter Queue): qué falló y el reencolado entrada a
 * entrada (RFC ux-calidad-datos #4).
 *
 * Antes era un número y un botón que respondía «Funcionalidad en desarrollo».
 * Ahora lista las entradas (abiertas o agotadas) desde `GET /admin/dlq` y cada
 * una se puede devolver a la cola con `POST /admin/dlq/{id}/reintentar`, con
 * confirmación. Reencolar NO ejecuta el conector en el momento: deja la entrada
 * lista para el próximo ciclo de reintentos de la ingesta, y el panel lo dice
 * así para no prometer un resultado inmediato. Sólo administradores; cada
 * reencolado queda auditado en el servidor.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA, getErrorMessage } from "@/lib/query-feedback";
import { analyticsKeys } from "@/lib/query-keys";
import { formatDate, formatNumber } from "@/lib/utils";

type Estado = "abiertas" | "agotadas";
type DlqListado = Schemas["DlqListado"];
type DlqReintento = Schemas["DlqReintento"];

const ESTADOS: { value: Estado; label: string }[] = [
  { value: "abiertas", label: "Abiertas" },
  { value: "agotadas", label: "Agotadas" },
];

const VACIO: Record<Estado, { title: string; hint: string }> = {
  abiertas: { title: "No hay entradas abiertas", hint: "La cola de errores está vacía." },
  agotadas: { title: "No hay entradas agotadas", hint: "Ninguna entrada ha gastado todos sus reintentos." },
};

const dlqKey = (estado: Estado) => ["admin", "dlq", estado] as const;

export function DlqCard() {
  const [estado, setEstado] = useState<Estado>("abiertas");
  const [confirmando, setConfirmando] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<DlqListado>({
    queryKey: dlqKey(estado),
    queryFn: () =>
      apiGet("/api/v1/admin/dlq", { params: { query: { estado, limit: 50 } } }) as Promise<DlqListado>,
    // El fallo (y el «sin permisos») se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const reintentar = useMutation({
    mutationFn: (id: number) =>
      apiMutate<DlqReintento>("POST", `/api/v1/admin/dlq/${id}/reintentar`),
    onSuccess: (res) => {
      if (res.reencolada) toast.success(res.detalle);
      else toast.info(res.detalle);
      void queryClient.invalidateQueries({ queryKey: ["admin", "dlq"] });
      void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
    },
    onError: (e: unknown) => {
      toast.error("No se pudo reencolar la entrada", { description: getErrorMessage(e, "accion") });
    },
    onSettled: () => setConfirmando(null),
  });

  const abiertas = (data?.resumen ?? []).reduce((s, r) => s + r.n, 0);
  const sinPermiso = error instanceof ApiError && error.status === 403;

  return (
    <Panel>
      <PanelTitle title="Cola de errores (DLQ)" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Extracciones que fallaron. Reencolar una entrada la devuelve al ciclo de reintentos de la ingesta: se
        reintenta en la próxima pasada, no al instante.
      </p>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p className="tf-tnum text-tf-title font-semibold">{formatNumber(abiertas)}</p>
                <p className="text-muted-foreground text-tf-meta">entradas abiertas en la cola</p>
              </>
            )}
          </div>
          <Segmented
            aria-label="Estado de las entradas"
            value={estado}
            options={ESTADOS}
            onChange={(siguiente) => {
              setEstado(siguiente);
              setConfirmando(null);
            }}
          />
        </div>

        {sinPermiso ? (
          <Aviso tone="info">Sólo los administradores pueden ver y reencolar la DLQ.</Aviso>
        ) : error ? (
          <PanelError
            variant="inline"
            title="No se pudo cargar la cola"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : !data?.items || data.items.length === 0 ? (
          <PanelEmpty size="sm" title={VACIO[estado].title} hint={VACIO[estado].hint} />
        ) : (
          <ul
            className="divide-y divide-border/60 rounded-md border border-border/60"
            aria-label={`Entradas ${estado} de la cola de errores`}
          >
            {data.items.map((item) => {
              const pidiendo = confirmando === item.id;
              return (
                <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-tf-body font-medium">
                      {item.fuente}
                      {item.scope ? <span className="text-muted-foreground"> · {item.scope}</span> : null}
                    </p>
                    <Pista contenido={item.error_message ?? undefined}>
                      <p className="text-muted-foreground truncate text-tf-meta">
                        {item.error_type ?? "Error"}: {item.error_message ?? "sin mensaje"}
                      </p>
                    </Pista>
                    <p className="text-muted-foreground text-tf-meta">
                      {formatNumber(item.retry_count)} reintentos · desde {formatDate(item.created_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {pidiendo && <span className="text-tf-meta text-warning">¿Confirmar?</span>}
                    <Button
                      size="sm"
                      variant={pidiendo ? "destructive" : "outline"}
                      disabled={reintentar.isPending}
                      aria-label={
                        pidiendo
                          ? `Confirmar reencolado de la entrada ${item.id}`
                          : `Reencolar la entrada ${item.id} (${item.fuente})`
                      }
                      onClick={() => {
                        if (!pidiendo) {
                          setConfirmando(item.id);
                          return;
                        }
                        reintentar.mutate(item.id);
                      }}
                    >
                      <RotateCcw aria-hidden="true" />
                      {pidiendo ? "Sí, reencolar" : "Reencolar"}
                    </Button>
                    {pidiendo && (
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
      </div>
    </Panel>
  );
}
