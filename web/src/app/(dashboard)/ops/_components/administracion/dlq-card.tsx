"use client";

/**
 * Dead Letter Queue: qué falló y el reencolado entrada a entrada (RFC
 * ux-calidad-datos #4).
 *
 * Antes era un número y un botón que respondía «Funcionalidad en desarrollo».
 * Ahora lista las entradas (abiertas o agotadas) desde `GET /admin/dlq` y cada
 * una se puede devolver a la cola con `POST /admin/dlq/{id}/reintentar`, con
 * confirmación. Reencolar NO ejecuta el conector en el momento: deja la entrada
 * lista para el próximo ciclo de reintentos de la ingesta, y la tarjeta lo dice
 * así para no prometer un resultado inmediato. Sólo administradores; cada
 * reencolado queda auditado en el servidor.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { analyticsKeys } from "@/lib/query-keys";
import { formatNumber } from "@/lib/utils";

type Estado = "abiertas" | "agotadas";
type DlqListado = Schemas["DlqListado"];
type DlqReintento = Schemas["DlqReintento"];

const ESTADOS: { valor: Estado; etiqueta: string }[] = [
  { valor: "abiertas", etiqueta: "Abiertas" },
  { valor: "agotadas", etiqueta: "Agotadas" },
];

const dlqKey = (estado: Estado) => ["admin", "dlq", estado] as const;

export function DlqCard() {
  const [estado, setEstado] = useState<Estado>("abiertas");
  const [confirmando, setConfirmando] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery<DlqListado>({
    queryKey: dlqKey(estado),
    queryFn: () =>
      apiGet("/api/v1/admin/dlq", { params: { query: { estado, limit: 50 } } }) as Promise<DlqListado>,
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
      toast.error(e instanceof Error ? e.message : "No se pudo reencolar la entrada");
    },
    onSettled: () => setConfirmando(null),
  });

  const abiertas = (data?.resumen ?? []).reduce((s, r) => s + r.n, 0);
  const sinPermiso = error instanceof ApiError && error.status === 403;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <RotateCcw className="h-5 w-5" aria-hidden="true" />
          Gestión de DLQ
        </CardTitle>
        <CardDescription>
          Dead Letter Queue — extracciones que fallaron. Reencolar una entrada la devuelve al ciclo
          de reintentos de la ingesta; se reintenta en la próxima pasada, no al instante.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p className="text-2xl font-bold tabular-nums">{formatNumber(abiertas)}</p>
                <p className="text-muted-foreground text-sm">entradas abiertas en la DLQ</p>
              </>
            )}
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Estado de las entradas">
            {ESTADOS.map((e) => (
              <Button
                key={e.valor}
                size="sm"
                variant={estado === e.valor ? "default" : "outline"}
                aria-pressed={estado === e.valor}
                onClick={() => {
                  setEstado(e.valor);
                  setConfirmando(null);
                }}
              >
                {e.etiqueta}
              </Button>
            ))}
          </div>
        </div>

        {sinPermiso ? (
          <p className="text-muted-foreground text-sm" role="status">
            Sólo los administradores pueden ver y reencolar la DLQ.
          </p>
        ) : error ? (
          <p className="text-destructive text-sm" role="alert">
            {(error as Error).message}
          </p>
        ) : isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : !data?.items || data.items.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="divide-y rounded-md border" aria-label={`Entradas ${estado} de la DLQ`}>
            {data.items.map((item) => {
              const pidiendo = confirmando === item.id;
              return (
                <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {item.fuente}
                      {item.scope ? <span className="text-muted-foreground"> · {item.scope}</span> : null}
                    </p>
                    <Pista contenido={item.error_message ?? undefined}>
                      <p className="text-muted-foreground truncate text-xs">
                        {item.error_type ?? "Error"}: {item.error_message ?? "sin mensaje"}
                      </p>
                    </Pista>
                    <p className="text-muted-foreground text-xs tabular-nums">
                      {formatNumber(item.retry_count)} reintentos · desde {item.created_at?.slice(0, 10) ?? "—"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {pidiendo && <span className="text-sm text-yellow-700 dark:text-yellow-400">¿Confirmar?</span>}
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
                      <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
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
      </CardContent>
    </Card>
  );
}
