"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { KpiCard } from "@/components/charts/kpi-card";
import { Activity, CheckCircle, XCircle, ExternalLink, Server } from "lucide-react";
import { formatDate } from "@/lib/utils";

interface HealthResponse {
  status?: string;
  version?: string;
  uptime?: number;
  [key: string]: unknown;
}

export default function ObservabilidadPage() {
  const {
    data: health,
    isLoading,
    isError,
    dataUpdatedAt,
  } = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: async () => {
      const res = await fetch("/api/v1/health", { credentials: "include" });
      if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
      return res.json();
    },
    refetchInterval: 30_000,
  });

  const isOnline = !!health && !isError;
  const lastCheck = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Observabilidad</h1>
        <p className="text-muted-foreground">
          Metricas de rendimiento, logs y estado del sistema.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid gap-4 md:grid-cols-3">
        <KpiCard
          title="Estado API"
          value={isLoading ? undefined : isOnline ? "Online" : "Offline"}
          subtitle={isOnline ? "Todos los servicios operativos" : "Error de conexion"}
          icon={Activity}
          loading={isLoading}
        />
        <KpiCard
          title="Ultimo health check"
          value={lastCheck ? lastCheck.toLocaleTimeString("es-ES") : undefined}
          subtitle={lastCheck ? formatDate(lastCheck) : undefined}
          icon={Server}
          loading={isLoading}
        />
        <KpiCard
          title="Version API"
          value={isLoading ? undefined : health?.version ?? "N/A"}
          icon={Server}
          loading={isLoading}
        />
      </div>

      <Separator />

      {/* System status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {isOnline ? (
              <CheckCircle className="h-5 w-5 text-green-600" />
            ) : isLoading ? (
              <Activity className="h-5 w-5 animate-pulse" />
            ) : (
              <XCircle className="h-5 w-5 text-red-600" />
            )}
            Estado del sistema
          </CardTitle>
          <CardDescription>
            Respuesta del endpoint /api/v1/health
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-5 w-1/2" />
            </div>
          ) : isError ? (
            <div className="flex items-center gap-2 text-destructive">
              <XCircle className="h-4 w-4" />
              <span>No se pudo conectar con la API. Verifica que el backend este activo.</span>
            </div>
          ) : (
            <div className="space-y-2">
              {Object.entries(health ?? {}).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between py-1">
                  <span className="text-sm font-medium text-muted-foreground">{key}</span>
                  <Badge variant="outline">
                    {typeof value === "object" ? JSON.stringify(value) : String(value)}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Grafana placeholder */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ExternalLink className="h-5 w-5" />
            Metricas Prometheus / Grafana
          </CardTitle>
          <CardDescription>
            Metricas detalladas disponibles en Grafana (puerto 3001)
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border-2 border-dashed p-8 text-center">
            <p className="text-muted-foreground mb-4">
              Panel de Grafana embebido (requiere configuracion de red)
            </p>
            <a
              href="http://localhost:3001"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-primary underline hover:no-underline"
            >
              <ExternalLink className="h-4 w-4" />
              Abrir Grafana en nueva pestana
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
