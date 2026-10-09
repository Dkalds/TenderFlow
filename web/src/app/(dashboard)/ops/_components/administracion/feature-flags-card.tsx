"use client";

/**
 * Feature flags: encender, apagar y graduar el despliegue de una funcionalidad.
 *
 * La lista la dirige el backend (`GET /feature-flags`), no un hardcode. Lo que
 * se edita aquí es un **borrador** sobre esa lista, y de él sale todo lo que la
 * pantalla anterior no sabía:
 *
 * - si hay algo por guardar (el botón estaba siempre activo);
 * - **qué** guardar: solo las flags que difieren del servidor. Antes viajaban
 *   todas, así que guardar pisaba el cambio que otro administrador hubiera
 *   hecho entretanto y dejaba un evento de auditoría por cada flag sin tocar;
 * - que el guardado terminó (no había confirmación).
 *
 * Comparte la clave de caché con `useFeatureFlag`, que es quien las lee en el
 * resto de la consola: al guardar, una flag apagada se nota al momento.
 *
 * Vive dentro de Administración —fue una vista propia para una lista que en
 * producción tiene una fila—, y por eso no lleva guarda: la pone la vista.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA, getErrorMessage } from "@/lib/query-feedback";
import { featureFlagKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils";

type FlagOut = Schemas["FlagOut"];

/** Lo que se puede cambiar de una flag. */
interface Ajuste {
  enabled: boolean;
  rollout_pct: number;
}

type Borrador = Record<string, Ajuste>;

const ajusteDe = (flag: FlagOut): Ajuste => ({ enabled: flag.enabled, rollout_pct: flag.rollout_pct });

/**
 * Dos ajustes apagados son el mismo ajuste: el despliegue de una flag apagada
 * no llega a nadie, así que encenderla y volver a apagarla no deja nada que
 * guardar aunque por el camino su porcentaje haya pasado de 0 a 100.
 */
const iguales = (a: Ajuste, b: Ajuste) =>
  a.enabled === b.enabled && (!a.enabled || a.rollout_pct === b.rollout_pct);

export function FeatureFlagsCard() {
  const queryClient = useQueryClient();
  const [borrador, setBorrador] = useState<Borrador>({});

  const { data, isLoading, error, refetch } = useQuery<FlagOut[]>({
    queryKey: featureFlagKeys.list,
    queryFn: () => apiGet("/api/v1/feature-flags"),
    // El fallo lo dice el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const flags = data ?? [];
  const efectivo = (flag: FlagOut): Ajuste => borrador[flag.flag] ?? ajusteDe(flag);
  const cambiadas = flags.filter((flag) => !iguales(efectivo(flag), ajusteDe(flag)));
  const hayCambios = cambiadas.length > 0;

  const editar = (flag: FlagOut, siguiente: Ajuste) => {
    setBorrador((previo) => {
      const resto = { ...previo };
      // Volver al valor del servidor no es un cambio: sale del borrador.
      if (iguales(siguiente, ajusteDe(flag))) delete resto[flag.flag];
      else resto[flag.flag] = siguiente;
      return resto;
    });
  };

  const alternar = (flag: FlagOut) => {
    const actual = efectivo(flag);
    const enabled = !actual.enabled;
    // Encender una flag que estaba al 0 % la dejaba «activa» sin llegar a
    // nadie: al encender, el despliegue arranca entero salvo que ya tuviera uno.
    const rollout_pct = enabled && actual.rollout_pct === 0 ? 100 : actual.rollout_pct;
    editar(flag, { enabled, rollout_pct });
  };

  const guardar = useMutation({
    mutationFn: (pendientes: FlagOut[]) =>
      apiMutate("PUT", "/api/v1/feature-flags", {
        flags: pendientes.map((flag) => ({ flag: flag.flag, ...efectivo(flag) })),
      }),
    onSuccess: (_respuesta, pendientes) => {
      // Lo guardado pasa a ser «lo del servidor» antes de soltar el borrador:
      // sin esto la lista volvía un instante a los valores viejos mientras
      // llegaba la relectura.
      const guardadas = new Map(pendientes.map((flag) => [flag.flag, efectivo(flag)]));
      queryClient.setQueryData<FlagOut[]>(featureFlagKeys.list, (previas) =>
        previas?.map((flag) => ({ ...flag, ...guardadas.get(flag.flag) })),
      );
      setBorrador({});
      void queryClient.invalidateQueries({ queryKey: featureFlagKeys.all });
      toast.success("Cambios guardados");
    },
  });

  // Cerrar o recargar la pestaña con cambios a medias los perdía sin avisar.
  useEffect(() => {
    if (!hayCambios) return;
    const avisar = (evento: BeforeUnloadEvent) => evento.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [hayCambios]);

  return (
    <Panel id="feature-flags">
      <PanelTitle
        as="h2"
        title="Feature flags"
        hint="Activa o desactiva funcionalidades y gradúa su despliegue"
        actions={
          flags.length > 0 && (
            <>
              {hayCambios && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setBorrador({})}
                  disabled={guardar.isPending}
                >
                  Descartar
                </Button>
              )}
              <Button
                size="sm"
                onClick={() => guardar.mutate(cambiadas)}
                disabled={!hayCambios || guardar.isPending}
              >
                {guardar.isPending ? "Guardando…" : "Guardar cambios"}
              </Button>
            </>
          )
        }
      />

      {hayCambios && (
        <p role="status" className="mb-3 text-tf-meta text-warning">
          {cambiadas.length} {cambiadas.length === 1 ? "cambio" : "cambios"} sin guardar
        </p>
      )}

      {guardar.error != null && (
        <Aviso tone="danger" title="No se pudieron guardar los cambios" className="mb-3">
          {getErrorMessage(guardar.error, "accion")}
        </Aviso>
      )}

      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los feature flags"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : flags.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="No hay feature flags definidos"
          hint="Cuando la instancia declare alguno, aparecerá aquí con su interruptor."
        />
      ) : (
        <ul className="divide-y divide-border/60">
          {flags.map((flag) => {
            const { enabled, rollout_pct } = efectivo(flag);
            return (
              <li key={flag.flag} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-0.5">
                    <h3 className="font-mono text-tf-body font-semibold">{flag.flag}</h3>
                    {flag.description && (
                      <p className="text-tf-meta text-muted-foreground">{flag.description}</p>
                    )}
                    {flag.updated_at && (
                      <p className="text-tf-meta text-muted-foreground">
                        Último cambio: {formatDate(flag.updated_at)}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-none items-center gap-3">
                    <Badge variant={enabled ? "success" : "secondary"} size="sm">
                      {enabled ? "Activo" : "Inactivo"}
                    </Badge>
                    <Switch
                      checked={enabled}
                      onCheckedChange={() => alternar(flag)}
                      aria-label={`Activar ${flag.flag}`}
                    />
                  </div>
                </div>
                {enabled && (
                  <div className="mt-3 flex items-center gap-4">
                    <span className="tf-tnum whitespace-nowrap text-tf-meta text-muted-foreground">
                      Despliegue: {rollout_pct} %
                    </span>
                    <Slider
                      value={[rollout_pct]}
                      onValueChange={([valor]) => editar(flag, { enabled, rollout_pct: valor })}
                      aria-label={`Despliegue gradual de ${flag.flag}`}
                      min={0}
                      max={100}
                      className="flex-1"
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
