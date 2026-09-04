"use client";

/**
 * Calidad de datos — completitud y consistencia del dataset.
 *
 * Vista compartida por la ruta `/calidad-datos` y por `?vista=calidad` del
 * espacio Ops. Ver la nota en `observabilidad-view.tsx` sobre por qué el
 * cuerpo no vive en el `page.tsx` de la ruta.
 */

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
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
import { CalibracionBajaBlock } from "@/components/calibracion-baja";
import { SourceFreshnessPanel } from "@/components/source-freshness-panel";
import {
  ShieldCheck,
  AlertTriangle,
  Clock,
  Database,
  Users,
  Boxes,
  CalendarClock,
} from "lucide-react";
import { fetchWithAuth } from "@/lib/api-client";
import { formatNumber, formatPercent, cn } from "@/lib/utils";
import { analyticsKeys } from "@/lib/query-keys";
const CalidadCompletenessChart = dynamic(() => import("@/components/charts/calidad-datos-charts").then(m => ({ default: m.CalidadCompletenessChart })), { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> });

interface ColumnCompleteness {
  columna: string;
  pct: number;
}

interface QualityData {
  total_records?: number;
  pct_cpv?: number;
  pct_importe?: number;
  pct_fecha?: number;
  pct_titulo?: number;
  completitud_columnas?: ColumnCompleteness[];
  // `null` = NO MEDIDO (ni `nif` ni `modulo_sap` son columnas de
  // `licitaciones`), y la tarjeta se abstiene. El backend devolvía el literal
  // 0.0, que la guarda `!= null` daba por bueno: la pantalla que existe para
  // acreditar la calidad del dato afirmaba una cobertura del 0,0 % que nadie
  // había medido.
  cobertura_nif?: number | null;
  cobertura_modulo_sap?: number | null;
  dlq_count?: number;
  pct_fecha_iso?: number;
  fechas_no_iso?: number;
  last_scrape_hours_ago?: number;
  last_scrape_at?: string;
  [key: string]: unknown;
}

function freshnessInfo(hours: number | null | undefined): {
  label: string;
  color: string;
  badge: "default" | "secondary" | "destructive";
} {
  if (hours == null) return { label: "N/A", color: "", badge: "secondary" };
  if (hours < 6)
    return { label: "Actualizado", color: "text-green-700", badge: "default" };
  if (hours <= 24)
    return { label: "Pendiente", color: "text-yellow-700", badge: "secondary" };
  return { label: "Obsoleto", color: "text-red-700", badge: "destructive" };
}

export default function CalidadDatosView() {
  const { data, isLoading, isError } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
  });

  const hoursAgo = data?.last_scrape_hours_ago ?? null;
  const freshness = freshnessInfo(hoursAgo);

  // Build chart data: prefer completitud_columnas, fallback to pct_* fields
  const chartData: ColumnCompleteness[] =
    data?.completitud_columnas && data.completitud_columnas.length > 0
      ? data.completitud_columnas
      : // Fallback a los `pct_*` sueltos. Se filtran los que el backend no
        // manda en vez de rellenarlos con 0: una barra a 0,0 % en la pantalla
        // de Calidad de Datos afirma que ninguna fila tiene título, que es la
        // misma cobertura inventada que #228 quitó de las dos tarjetas de
        // arriba. Sin dato, la columna no entra en el gráfico.
        (
          [
            { columna: "Título", pct: data?.pct_titulo },
            { columna: "CPV", pct: data?.pct_cpv },
            { columna: "Importe", pct: data?.pct_importe },
            { columna: "Fecha", pct: data?.pct_fecha },
          ] as { columna: string; pct?: number | null }[]
        )
          .filter((c): c is { columna: string; pct: number } => c.pct != null)
          .map((c) => ({ columna: c.columna, pct: c.pct }));

  const dlqCount = data?.dlq_count ?? 0;
  const fechasNoIso = data?.fechas_no_iso ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Calidad de Datos</h1>
        <p className="text-muted-foreground">
          Completitud y consistencia del dataset.
        </p>
      </div>

      {isError && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-destructive">
            Error al cargar métricas de calidad. Verifica que la API esté activa.
          </CardContent>
        </Card>
      )}

      {/* KPI row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total registros"
          value={
            data?.total_records != null
              ? formatNumber(data.total_records)
              : undefined
          }
          icon={Database}
          loading={isLoading}
        />
        <KpiCard
          title="Cobertura NIF"
          value={
            data?.cobertura_nif != null
              ? formatPercent(data.cobertura_nif)
              : undefined
          }
          subtitle={
            !isLoading && data?.cobertura_nif == null ? "sin medir" : undefined
          }
          icon={Users}
          loading={isLoading}
        />
        <KpiCard
          title="Cobertura Módulo SAP"
          value={
            data?.cobertura_modulo_sap != null
              ? formatPercent(data.cobertura_modulo_sap)
              : undefined
          }
          subtitle={
            !isLoading && data?.cobertura_modulo_sap == null
              ? "sin medir"
              : undefined
          }
          icon={Boxes}
          loading={isLoading}
        />
        <KpiCard
          title="Frescura scraping"
          value={
            isLoading
              ? undefined
              : hoursAgo != null
                ? `${hoursAgo}h`
                : "N/A"
          }
          subtitle={freshness.label}
          icon={Clock}
          loading={isLoading}
          className={cn(
            !isLoading &&
              hoursAgo != null &&
              hoursAgo > 24 &&
              "border-red-200 dark:border-red-800",
            !isLoading &&
              hoursAgo != null &&
              hoursAgo > 6 &&
              hoursAgo <= 24 &&
              "border-yellow-200 dark:border-yellow-800",
          )}
        />
      </div>

      <Separator />

      <SourceFreshnessPanel />

      {/* Completeness horizontal bar chart */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" />
            Completitud por columna
          </CardTitle>
          <CardDescription>
            Porcentaje de registros con campos completos
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          ) : (
            <CalidadCompletenessChart data={chartData} />
          )}
        </CardContent>
      </Card>

      {/* Date format consistency — formato, NO completitud (una fecha presente
          pero DD/MM/YYYY cuenta como completa arriba, pero no-ISO aquí) */}
      <Card
        className={cn(
          fechasNoIso > 0 &&
            "border-amber-500 bg-amber-50/50 dark:bg-amber-950/20",
        )}
      >
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarClock
              className={cn(
                "h-4 w-4",
                fechasNoIso > 0 ? "text-amber-600" : "text-muted-foreground",
              )}
            />
            Consistencia de formato de fecha
          </CardTitle>
          <CardDescription>
            Fechas de publicación en ISO-8601 (mide formato, no completitud)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-8 w-24" />
          ) : (
            <>
              <p
                className={cn(
                  "text-2xl font-bold",
                  fechasNoIso > 0 && "text-amber-600",
                )}
              >
                {data?.pct_fecha_iso != null
                  ? formatPercent(data.pct_fecha_iso)
                  : "N/A"}
              </p>
              <p className="text-sm text-muted-foreground">
                {fechasNoIso > 0
                  ? `${formatNumber(fechasNoIso)} fecha(s) en formato no-ISO (p. ej. DD/MM/YYYY)`
                  : "Todas las fechas presentes en formato ISO"}
              </p>
              {fechasNoIso > 0 && (
                <Badge variant="secondary" className="mt-2">
                  Revisar normalización
                </Badge>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* DLQ + Scrape freshness */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card
          className={cn(
            dlqCount > 0 &&
              "border-red-500 bg-red-50/50 dark:bg-red-950/20",
          )}
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle
                className={cn(
                  "h-4 w-4",
                  dlqCount > 0 ? "text-red-600" : "text-muted-foreground",
                )}
              />
              Dead Letter Queue (DLQ)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p
                  className={cn(
                    "text-2xl font-bold",
                    dlqCount > 0 && "text-red-600",
                  )}
                >
                  {dlqCount}
                </p>
                <p className="text-sm text-muted-foreground">
                  registros en cola de errores
                </p>
                {dlqCount > 0 && (
                  <Badge variant="destructive" className="mt-2">
                    Requiere atención
                  </Badge>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card
          className={cn(
            hoursAgo != null &&
              hoursAgo > 24 &&
              "border-red-500",
            hoursAgo != null &&
              hoursAgo > 6 &&
              hoursAgo! <= 24 &&
              "border-yellow-500",
          )}
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4" />
              Frescura del scraping
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <>
                <p className="text-2xl font-bold">
                  {hoursAgo != null ? `${hoursAgo} horas` : "N/A"}
                </p>
                <p className="text-sm text-muted-foreground">
                  desde la última ingesta
                </p>
                <Badge variant={freshness.badge} className="mt-2">
                  {freshness.label}
                </Badge>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Weekly pipeline summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" />
            Resumen del pipeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-8 w-32" />
          ) : (
            <div className="flex items-center gap-4">
              <div>
                <p className="text-2xl font-bold">
                  {formatNumber(data?.total_records)}
                </p>
                <p className="text-sm text-muted-foreground">
                  registros totales en el sistema
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Calibración del modelo de baja — closed loop predicción vs. realidad */}
      <CalibracionBajaBlock />
    </div>
  );
}
