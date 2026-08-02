"use client";

import { useState, useEffect } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Info, RefreshCw } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/auth";
import { formatDate } from "@/lib/utils";

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

export default function FeatureFlagsPage() {
  const { isAdmin } = useSession();
  // La lista la dirige el backend (no un hardcode): se rellena desde la API.
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [apiAvailable, setApiAvailable] = useState(false);

  // Fetch flags from API on mount
  useEffect(() => {
    const fetchFlags = async () => {
      try {
        const res = await fetch("/api/v1/feature-flags", {
          credentials: "include",
        });
        if (!res.ok) return;
        const data: ApiFlag[] = await res.json();
        setApiAvailable(true);
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
      } catch {
        // API no disponible: lista vacía (no hay fallback hardcodeado).
      }
    };
    fetchFlags();
  }, []);

  const toggleFlag = (key: string) => {
    setFlags((prev) =>
      prev.map((f) => (f.key === key ? { ...f, defaultEnabled: !f.defaultEnabled, enabled: !f.enabled } : f)),
    );
  };

  const setRollout = (key: string, value: number) => {
    setFlags((prev) =>
      prev.map((f) => (f.key === key ? { ...f, rollout: value } : f)),
    );
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
      const res = await fetch("/api/v1/feature-flags", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flags: payload }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? "Error al sincronizar");
      }
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "Error de conexion");
    } finally {
      setSyncing(false);
    }
  };

  const enabled = (f: FeatureFlag) => f.enabled ?? f.defaultEnabled;
  const rollout = (f: FeatureFlag) => f.rollout ?? (enabled(f) ? 100 : 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="sr-only">Feature Flags</h1>
          <p className="text-muted-foreground">
            Toggles de funcionalidades en tiempo real
            {apiAvailable ? " (sincronizado con API)" : " (local)"}.
          </p>
        </div>
        {isAdmin && apiAvailable && (
          <Button
            variant="outline"
            onClick={syncToApi}
            disabled={syncing}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            Sincronizar
          </Button>
        )}
      </div>

      {syncError && (
        <Card className="bg-destructive/10 border-destructive/30">
          <CardContent className="pt-4 text-sm text-destructive">
            {syncError}
          </CardContent>
        </Card>
      )}

      {!apiAvailable && (
        <Card className="bg-amber-50/50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800">
          <CardContent className="pt-4 flex items-start gap-2 text-sm">
            <Info className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
            <span>
              API de feature flags no disponible. No se muestran flags hasta poder
              conectar con el backend.
            </span>
          </CardContent>
        </Card>
      )}

      {apiAvailable && flags.length === 0 && (
        <Card>
          <CardContent className="pt-4 text-sm text-muted-foreground">
            No hay feature flags definidos en el backend.
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {flags.map((flag) => {
          const isOn = enabled(flag);
          const r = rollout(flag);

          return (
            <Card key={flag.key}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-base font-mono">
                      {flag.key}
                    </CardTitle>
                    <CardDescription>{flag.description}</CardDescription>
                    {flag.updatedAt && (
                      <p className="text-xs text-muted-foreground">
                        Último cambio: {formatDate(flag.updatedAt)}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={isOn ? "default" : "secondary"}>
                      {isOn ? "ON" : "OFF"}
                    </Badge>
                    <Switch
                      checked={isOn}
                      onCheckedChange={() => toggleFlag(flag.key)}
                      aria-label={`Toggle ${flag.key}`}
                    />
                  </div>
                </div>
              </CardHeader>
              {isOn && (
                <CardContent>
                  <div className="flex items-center gap-4">
                    <label className="text-sm text-muted-foreground whitespace-nowrap">
                      Rollout: {r}%
                    </label>
                    <Slider
                      value={[r]}
                      onValueChange={([v]) => setRollout(flag.key, v)}
                      min={0}
                      max={100}
                      className="flex-1"
                    />
                  </div>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
