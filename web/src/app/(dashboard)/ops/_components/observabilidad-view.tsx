"use client";

/**
 * Observabilidad — salud de infraestructura y servicios (SRE).
 *
 * El cuerpo vive aquí y no en `observabilidad/page.tsx` porque lo montan dos
 * entradas: la ruta propia y la vista `?vista=observabilidad` del espacio Ops.
 * Antes `/ops` importaba el `page.tsx` de la ruta, así que ese módulo tenía dos
 * papeles a la vez (boundary de ruta y componente) y Next no podía tratarlo
 * como lo primero.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { KpiCard } from "@/components/charts/kpi-card";
import {
  Activity,
  CheckCircle,
  XCircle,
  ExternalLink,
  Server,
  AlertTriangle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { formatDate, formatNumber, formatTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { getGrafanaUrl } from "@/lib/runtime-config";

interface HealthCheck {
  status?: string;
  detail?: string;
  [key: string]: unknown;
}

interface HealthResponse {
  status?: string;
  version?: string;
  uptime?: number;
  checks?: Record<string, HealthCheck | string>;
  [key: string]: unknown;
}

interface QualityData {
  dlq_count?: number;
  [key: string]: unknown;
}

function StatusDot({ status }: { status: "ok" | "warn" | "error" }) {
  const label = status === "ok" ? "Saludable" : status === "warn" ? "Verificando" : "Error";
  return (
    <span
      className={cn(
        "inline-block h-3 w-3 rounded-full",
        status === "ok" && "bg-green-500",
        status === "warn" && "bg-yellow-500",
        status === "error" && "bg-red-500",
      )}
      aria-label={`Estado: ${label}`}
      title={label}
    />
  );
}

function deriveComponentStatus(value: unknown): "ok" | "error" {
  if (typeof value === "string") {
    const lower = value.toLowerCase();
    return lower === "ok" || lower === "connected" || lower === "healthy"
      ? "ok"
      : "error";
  }
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    const s = String(obj.status ?? "").toLowerCase();
    return s === "ok" || s === "connected" || s === "healthy" ? "ok" : "error";
  }
  return "error";
}

function deriveComponentDetail(key: string, value: unknown): string {
  if (typeof value === "string") return `${key}: ${value}`;
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    return obj.detail ? String(obj.detail) : `${key}: ${obj.status ?? "unknown"}`;
  }
  return `${key}: ${String(value)}`;
}

export default function ObservabilidadView() {
  const {
    data: health,
    isLoading,
    isError,
    isFetching,
    dataUpdatedAt,
    refetch,
  } = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: async () => {
      const res = await fetch("/api/v1/health", { credentials: "include" });
      if (res.status === 401) throw new Error("Sesión expirada");
      if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
      return res.json();
    },
    refetchInterval: 30_000,
  });

  const { data: quality } = useQuery<QualityData>({
    queryKey: ["analytics-quality-obs"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/quality", { credentials: "include" });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
    refetchInterval: 30_000,
  });

  const isOnline = !!health && !isError;
  const lastCheck = dataUpdatedAt ? new Date(dataUpdatedAt) : null;
  const overallStatus: "ok" | "warn" | "error" = isLoading
    ? "warn"
    : isOnline
      ? "ok"
      : "error";

  // Extract component checks from health response
  const checks: Record<string, unknown> = {};
  if (health) {
    // If health.checks exists, use it; otherwise look for top-level keys
    if (health.checks && typeof health.checks === "object") {
      Object.assign(checks, health.checks);
    } else {
      for (const k of Object.keys(health)) {
        if (
          !["status", "version", "uptime"].includes(k) &&
          typeof health[k] === "object" &&
          health[k] !== null
        ) {
          checks[k] = health[k];
        }
        if (["db", "redis", "disk"].includes(k) && typeof health[k] === "string") {
          checks[k] = health[k];
        }
      }
    }
  }

  const dlqCount = quality?.dlq_count ?? 0;
  const grafanaUrl = getGrafanaUrl();

  const handleRetryDlq = () => {
    toast.info("Funcionalidad en desarrollo: Reintentar DLQ");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="sr-only">Observabilidad</h1>
          <p className="text-muted-foreground">
            Salud de infraestructura y servicios (SRE). Para la integridad del
            dato (completitud, DLQ, drops de escritura) ve a{" "}
            <Link
              href="/calidad-datos"
              className="font-medium underline underline-offset-2 hover:text-foreground"
            >
              Calidad de Datos
            </Link>
            .
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          aria-label="Refrescar estado del sistema"
        >
          <RefreshCw
            className={cn("mr-2 h-4 w-4", isFetching && "animate-spin")}
          />
          Refrescar
        </Button>
      </div>

      {/* Run KPIs */}
      <div className="grid gap-4 md:grid-cols-3">
        <KpiCard
          title="Estado API"
          value={
            isLoading ? undefined : isOnline ? "Online" : "Offline"
          }
          subtitle={
            isOnline
              ? "Todos los servicios operativos"
              : isError
                ? "Error de conexión"
                : undefined
          }
          icon={Activity}
          loading={isLoading}
          className={cn(
            !isLoading && isOnline && "border-green-200 dark:border-green-800",
            !isLoading && !isOnline && "border-red-200 dark:border-red-800",
          )}
        />
        <KpiCard
          title="Último health check"
          value={lastCheck ? formatTime(lastCheck) : undefined}
          subtitle={lastCheck ? formatDate(lastCheck) : undefined}
          icon={Server}
          loading={isLoading}
        />
        <KpiCard
          title="Versión API"
          value={isLoading ? undefined : health?.version ?? "N/A"}
          icon={Server}
          loading={isLoading}
        />
      </div>

      {/* Status indicator row */}
      {!isLoading && (
        <div className="flex items-center gap-3 text-sm">
          <StatusDot status={overallStatus} />
          <span className="font-medium">
            {overallStatus === "ok"
              ? "Sistema operativo"
              : overallStatus === "warn"
                ? "Verificando…"
                : "Sistema con errores"}
          </span>
          {lastCheck && (
            <span className="text-muted-foreground">
              — Verificado {formatTime(lastCheck)}
            </span>
          )}
        </div>
      )}

      <Separator />

      {/* Component health grid */}
      {Object.keys(checks).length > 0 && (
        <>
          <h2 className="text-xl font-semibold">Componentes</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(checks).map(([key, value]) => {
              const compStatus = deriveComponentStatus(value);
              const detail = deriveComponentDetail(key, value);
              return (
                <Card key={key}>
                  <CardContent className="pt-5">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium capitalize">{key}</span>
                      <Badge
                        variant={compStatus === "ok" ? "default" : "destructive"}
                        className={cn(
                          compStatus === "ok" &&
                            "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
                        )}
                      >
                        {compStatus === "ok" ? "OK" : "Error"}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{detail}</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
          <Separator />
        </>
      )}

      {/* System status raw */}
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
              <span>
                No se pudo conectar con la API. Verifica que el backend esté activo.
              </span>
            </div>
          ) : (
            <div className="space-y-2">
              {Object.entries(health ?? {}).map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-center justify-between py-1"
                >
                  <span className="text-sm font-medium text-muted-foreground">
                    {key}
                  </span>
                  <Badge variant="outline">
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* DLQ Section */}
      <Card
        className={cn(
          dlqCount > 0 &&
            "border-yellow-500 bg-yellow-50/50 dark:bg-yellow-950/20",
        )}
      >
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle
              className={cn(
                "h-4 w-4",
                dlqCount > 0 ? "text-yellow-600" : "text-muted-foreground",
              )}
            />
            Dead Letter Queue (DLQ)
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div>
            <p className="text-2xl font-bold">{formatNumber(dlqCount)}</p>
            <p className="text-sm text-muted-foreground">
              registros en cola de errores
            </p>
            {dlqCount > 0 && (
              <Badge variant="destructive" className="mt-2">
                Requiere atención
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button asChild variant="outline">
              <Link href="/calidad-datos">
                <ShieldCheck className="mr-2 h-4 w-4" />
                Inspeccionar DLQ
              </Link>
            </Button>
            <Button
              variant="outline"
              onClick={handleRetryDlq}
              disabled={dlqCount === 0}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Reintentar DLQ
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Grafana link */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ExternalLink className="h-5 w-5" />
            Métricas Prometheus / Grafana
          </CardTitle>
          <CardDescription>
            Métricas detalladas disponibles en Grafana
          </CardDescription>
        </CardHeader>
        <CardContent>
          {grafanaUrl ? (
            <Button asChild>
              <a href={grafanaUrl} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="mr-2 h-4 w-4" />
                Abrir Grafana
              </a>
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              URL de Grafana no configurada. Define{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                NEXT_PUBLIC_GRAFANA_URL
              </code>{" "}
              en el entorno del frontend para habilitar el enlace.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
