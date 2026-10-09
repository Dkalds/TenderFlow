"use client";

/**
 * Cola de errores de la ingesta (Dead Letter Queue): qué falló, de qué está
 * hecha la cola y las dos salidas de cada entrada (RFC ux-calidad-datos #4).
 *
 * - **Reencolar** la devuelve al ciclo de reintentos. NO ejecuta el conector en
 *   el momento: la deja lista para la próxima pasada, y el panel lo dice así
 *   para no prometer un resultado inmediato.
 * - **Descartar** la cierra sin reintentarla. Es la salida de lo que un
 *   reintento no arregla —un error de esquema de una versión que ya no existe
 *   falla igual en cada pasada—; sin ella esas entradas no salían nunca, y el
 *   aviso en rojo de la cola no se podía apagar.
 *
 * Las dos piden confirmación y quedan auditadas en el servidor. El desglose por
 * tipo de error cuenta abiertas **y** agotadas: es lo que dice cuál de las dos
 * salidas tiene sentido antes de ir entrada por entrada.
 *
 * Sólo administradores.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA, getErrorMessage } from "@/lib/query-feedback";
import { adminKeys, analyticsKeys } from "@/lib/query-keys";
import { formatDate, formatNumber } from "@/lib/utils";

type Estado = "abiertas" | "agotadas";
type Accion = "reencolar" | "descartar";
type DlqListado = Schemas["DlqListado"];
type DlqReintento = Schemas["DlqReintento"];
type DlqDescarte = Schemas["DlqDescarte"];

const VACIO: Record<Estado, { title: string; hint: string }> = {
  abiertas: { title: "No hay entradas abiertas", hint: "Nada espera a un reintento." },
  agotadas: { title: "No hay entradas agotadas", hint: "Ninguna entrada ha gastado todos sus reintentos." },
};

const ETIQUETA: Record<Accion, { pedir: string; confirmar: string }> = {
  reencolar: { pedir: "Reencolar", confirmar: "Sí, reencolar" },
  descartar: { pedir: "Descartar", confirmar: "Sí, descartar" },
};

export function DlqCard() {
  const [estado, setEstado] = useState<Estado>("abiertas");
  // Una sola confirmación armada a la vez, entre todas las filas y las dos
  // acciones: con dos, un segundo clic distraído ejecuta la que no se miraba.
  const [confirmando, setConfirmando] = useState<{ id: number; accion: Accion } | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<DlqListado>({
    queryKey: adminKeys.dlq.estado(estado),
    queryFn: () =>
      apiGet("/api/v1/admin/dlq", { params: { query: { estado, limit: 50 } } }) as Promise<DlqListado>,
    // El fallo (y el «sin permisos») se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const alTerminar = () => {
    void queryClient.invalidateQueries({ queryKey: adminKeys.dlq.all });
    void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
  };

  const reintentar = useMutation({
    mutationFn: (id: number) => apiMutate<DlqReintento>("POST", `/api/v1/admin/dlq/${id}/reintentar`),
    onSuccess: (res) => {
      if (res.reencolada) toast.success(res.detalle);
      else toast.info(res.detalle);
      alTerminar();
    },
    onError: (e: unknown) => {
      toast.error("No se pudo reencolar la entrada", { description: getErrorMessage(e, "accion") });
    },
    onSettled: () => setConfirmando(null),
  });

  const descartar = useMutation({
    mutationFn: (id: number) => apiMutate<DlqDescarte>("POST", `/api/v1/admin/dlq/${id}/descartar`),
    onSuccess: (res) => {
      if (res.descartada) toast.success(res.detalle);
      else toast.info(res.detalle);
      alTerminar();
    },
    onError: (e: unknown) => {
      toast.error("No se pudo descartar la entrada", { description: getErrorMessage(e, "accion") });
    },
    onSettled: () => setConfirmando(null),
  });

  const ocupado = reintentar.isPending || descartar.isPending;
  const errores = data?.resumen_errores ?? [];
  const abiertas = (data?.resumen ?? []).reduce((s, r) => s + r.n, 0);
  const agotadas = errores.reduce((s, r) => s + r.agotadas, 0);
  const sinPermiso = error instanceof ApiError && error.status === 403;

  return (
    <Panel>
      <PanelTitle as="h2" title="Cola de errores de la ingesta" />
      <p className="mb-3 max-w-prose text-tf-meta text-muted-foreground">
        Extracciones que fallaron. Reencolar devuelve la entrada al ciclo de reintentos: se reintenta en la
        próxima pasada, no al instante. Descartar la cierra sin reintentarla, para lo que un reintento no va a
        arreglar.
      </p>
      <div className="space-y-4">
        <Segmented
          aria-label="Estado de las entradas"
          value={estado}
          // Sin respuesta no hay recuento: un «0» afirmaría una cola vacía que
          // nadie ha medido.
          options={[
            { value: "abiertas", label: "Abiertas", count: data ? formatNumber(abiertas) : undefined },
            { value: "agotadas", label: "Agotadas", count: data ? formatNumber(agotadas) : undefined },
          ]}
          onChange={(siguiente) => {
            setEstado(siguiente);
            setConfirmando(null);
          }}
        />

        {errores.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-tf-meta text-muted-foreground">Sin resolver, por tipo de error</span>
            <ul aria-label="Entradas sin resolver por tipo de error" className="flex flex-wrap gap-1.5">
              {errores.map((e) => (
                <li key={e.error_type}>
                  <Badge variant="outline" size="sm" className="font-mono">
                    {e.error_type || "sin tipo"} <span className="tf-tnum ml-1">{formatNumber(e.n)}</span>
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}

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
              const armada = confirmando?.id === item.id ? confirmando.accion : null;
              const boton = (accion: Accion) => {
                const pidiendo = armada === accion;
                const nombre =
                  accion === "reencolar"
                    ? pidiendo
                      ? `Confirmar reencolado de la entrada ${item.id}`
                      : `Reencolar la entrada ${item.id} (${item.fuente})`
                    : pidiendo
                      ? `Confirmar descarte de la entrada ${item.id}`
                      : `Descartar la entrada ${item.id} (${item.fuente})`;
                return (
                  <Button
                    size="sm"
                    variant={pidiendo ? "destructive" : accion === "reencolar" ? "outline" : "ghost"}
                    disabled={ocupado}
                    aria-label={nombre}
                    onClick={() => {
                      if (!pidiendo) {
                        setConfirmando({ id: item.id, accion });
                        return;
                      }
                      (accion === "reencolar" ? reintentar : descartar).mutate(item.id);
                    }}
                  >
                    {accion === "reencolar" && <RotateCcw aria-hidden="true" />}
                    {pidiendo ? ETIQUETA[accion].confirmar : ETIQUETA[accion].pedir}
                  </Button>
                );
              };
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
                    {armada && <span className="text-tf-meta text-warning">¿Confirmar?</span>}
                    {armada !== "descartar" && boton("reencolar")}
                    {armada !== "reencolar" && boton("descartar")}
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
      </div>
    </Panel>
  );
}
