"use client";

/**
 * Feature flags — toggles de funcionalidad, sincronizados con el backend.
 *
 * Vista compartida por la ruta `/feature-flags` y por `?vista=flags` del
 * espacio Ops. La guarda de administrador viaja con la vista (ver la nota en
 * `administracion-view.tsx`).
 */

import { useEffect, useState } from "react";
import { Aviso, Panel, PanelEmpty, PanelError } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/query-feedback";
import { AdminGuard } from "@/components/admin-guard";

interface FeatureFlag {
  key: string;
  description: string;
  defaultEnabled: boolean;
  enabled?: boolean;
  rollout?: number;
  updatedAt?: string | null;
}

interface ApiFlag {
  flag: string;
  enabled: boolean;
  rollout_pct: number;
  description: string;
  updated_at?: string | null;
}

export default function FeatureFlagsView() {
  return (
    <AdminGuard>
      <FeatureFlagsContent />
    </AdminGuard>
  );
}

function FeatureFlagsContent() {
  const { isAdmin } = useSession();
  // La lista la dirige el backend (no un hardcode): se rellena desde la API.
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  // `cargando` hasta la primera respuesta: antes el aviso de «no disponible»
  // se pintaba mientras la petición seguía en vuelo.
  const [carga, setCarga] = useState<"cargando" | "lista" | "error">("cargando");
  const [errorCarga, setErrorCarga] = useState<unknown>(null);
  // Cada «Reintentar» sube el contador y vuelve a lanzar la carga.
  const [intento, setIntento] = useState(0);

  useEffect(() => {
    let vigente = true;
    fetchWithAuth<ApiFlag[]>("/api/v1/feature-flags").then(
      (data) => {
        if (!vigente) return;
        // Render exactamente lo que devuelve el backend (fuente de verdad).
        setFlags(
          data.map((a) => ({
            key: a.flag,
            description: a.description,
            defaultEnabled: a.enabled,
            enabled: a.enabled,
            rollout: a.rollout_pct,
            updatedAt: a.updated_at,
          })),
        );
        setCarga("lista");
      },
      (err: unknown) => {
        if (!vigente) return;
        // Sin respuesta, lista vacía: no hay fallback hardcodeado.
        setErrorCarga(err);
        setCarga("error");
      },
    );
    return () => {
      vigente = false;
    };
  }, [intento]);

  const toggleFlag = (key: string) => {
    setFlags((prev) =>
      prev.map((f) => (f.key === key ? { ...f, defaultEnabled: !f.defaultEnabled, enabled: !f.enabled } : f)),
    );
  };

  const setRollout = (key: string, value: number) => {
    setFlags((prev) => prev.map((f) => (f.key === key ? { ...f, rollout: value } : f)));
  };

  const syncToApi = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      const payload = flags.map((f) => ({
        flag: f.key,
        enabled: f.enabled ?? f.defaultEnabled,
        rollout_pct: f.rollout ?? (f.enabled ?? f.defaultEnabled ? 100 : 0),
      }));
      // `apiMutate` ya adjunta el CSRF y extrae el `detail` RFC-7807; el
      // ensamblado a mano de la cabecera era una copia local de eso mismo.
      await apiMutate("PUT", "/api/v1/feature-flags", { flags: payload });
    } catch (err) {
      setSyncError(getErrorMessage(err, "accion"));
    } finally {
      setSyncing(false);
    }
  };

  const enabled = (f: FeatureFlag) => f.enabled ?? f.defaultEnabled;
  const rollout = (f: FeatureFlag) => f.rollout ?? (enabled(f) ? 100 : 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="sr-only">Feature flags</h1>
          <p className="text-tf-meta text-muted-foreground">
            Activa o desactiva funcionalidades y su despliegue gradual. Los cambios se aplican al guardar.
          </p>
        </div>
        {isAdmin && carga === "lista" && (
          <Button size="sm" variant="outline" onClick={syncToApi} disabled={syncing}>
            {syncing ? "Guardando…" : "Guardar cambios"}
          </Button>
        )}
      </div>

      {syncError && (
        <Aviso tone="danger" title="No se pudieron guardar los cambios">
          {syncError}
        </Aviso>
      )}

      {carga === "cargando" && (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-20 w-full rounded-xl" />
        </div>
      )}

      {carga === "error" && (
        <PanelError
          title="No se pudieron cargar los feature flags"
          error={errorCarga}
          onRetry={() => {
            setCarga("cargando");
            setIntento((n) => n + 1);
          }}
        />
      )}

      {carga === "lista" && flags.length === 0 && (
        <PanelEmpty
          title="No hay feature flags definidos"
          hint="Cuando la instancia declare alguno, aparecerá aquí con su interruptor."
        />
      )}

      <div className="space-y-3">
        {flags.map((flag) => {
          const isOn = enabled(flag);
          const r = rollout(flag);

          return (
            <Panel key={flag.key}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-0.5">
                  <h3 className="font-mono text-tf-body font-semibold">{flag.key}</h3>
                  <p className="text-tf-meta text-muted-foreground">{flag.description}</p>
                  {flag.updatedAt && (
                    <p className="text-tf-meta text-muted-foreground">Último cambio: {formatDate(flag.updatedAt)}</p>
                  )}
                </div>
                <div className="flex flex-none items-center gap-3">
                  <Badge variant={isOn ? "success" : "secondary"} size="sm">
                    {isOn ? "Activo" : "Inactivo"}
                  </Badge>
                  <Switch
                    checked={isOn}
                    onCheckedChange={() => toggleFlag(flag.key)}
                    aria-label={`Activar ${flag.key}`}
                  />
                </div>
              </div>
              {isOn && (
                <div className="mt-3 flex items-center gap-4">
                  <span className="tf-tnum whitespace-nowrap text-tf-meta text-muted-foreground">
                    Despliegue: {r} %
                  </span>
                  <Slider
                    value={[r]}
                    onValueChange={([v]) => setRollout(flag.key, v)}
                    aria-label={`Despliegue gradual de ${flag.key}`}
                    min={0}
                    max={100}
                    className="flex-1"
                  />
                </div>
              )}
            </Panel>
          );
        })}
      </div>
    </div>
  );
}
