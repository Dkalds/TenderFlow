"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Building2, CalendarDays, Eye, EyeOff, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { useFilters } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/utils";

import { CompanyAwards } from "./company-awards";
import { CompanyProfileSummary } from "./company-profile-summary";
import type { CompanyProfileData } from "./company-profile-types";

type Period = "12m" | "3y" | "all" | "global";

export function initialCompanyProfilePeriod(hasGlobalPeriod: boolean): Period {
  return hasGlobalPeriod ? "global" : "all";
}

interface CompanyProfileProps {
  empresaId: number;
  /** IDs adicionales del grupo cuando el competidor agrega varias identidades del maestro. */
  groupIds?: number[];
}

function dateDaysAgo(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return value.toISOString().slice(0, 10);
}

function ProfileSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-44 w-full rounded-xl" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-32 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-80 w-full rounded-lg" />
    </div>
  );
}

export function CompanyProfile({ empresaId, groupIds }: CompanyProfileProps) {
  const filters = useFilters();
  const hasGlobalPeriod = Boolean(filters.rango.desde || filters.rango.hasta);
  const [period, setPeriod] = useState<Period>(() => initialCompanyProfilePeriod(hasGlobalPeriod));
  const queryClient = useQueryClient();
  // El dossier agrega la actividad de todo el grupo; el usuario nunca elige
  // cuál identidad abrir.
  const allIds = useMemo(() => [...new Set([empresaId, ...(groupIds ?? [])])], [empresaId, groupIds]);

  const scopeQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (allIds.length > 1) params.set("empresa_ids", allIds.join(","));
    if (filters.ccaas.length) params.set("ccaa", filters.ccaas.join(","));
    if (filters.tecnologias.length) params.set("tecnologia", filters.tecnologias.join(","));
    if (filters.importeMin != null) params.set("importe_min", String(filters.importeMin));

    if (period === "global") {
      if (filters.rango.desde) params.set("fecha_desde", filters.rango.desde);
      if (filters.rango.hasta) params.set("fecha_hasta", filters.rango.hasta);
    } else if (period === "12m") {
      params.set("fecha_desde", dateDaysAgo(364));
      params.set("fecha_hasta", new Date().toISOString().slice(0, 10));
    } else if (period === "3y") {
      params.set("fecha_desde", dateDaysAgo(1095));
      params.set("fecha_hasta", new Date().toISOString().slice(0, 10));
    }
    return params.toString();
  }, [allIds, filters.ccaas, filters.importeMin, filters.rango.desde, filters.rango.hasta, filters.tecnologias, period]);

  const {
    data: profile,
    isLoading,
    error,
  } = useQuery<CompanyProfileData>({
    queryKey: ["competitive-company-profile", empresaId, scopeQuery],
    queryFn: () =>
      fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/perfil${scopeQuery ? `?${scopeQuery}` : ""}`),
    staleTime: 5 * 60 * 1000,
  });

  const { data: watchlist } = useQuery<{ items: { empresa_id: number }[] }>({
    queryKey: ["watchlist-empresas"],
    queryFn: () => fetchWithAuth("/api/v1/competitive/watchlist"),
    staleTime: 60 * 1000,
  });
  const watched = (watchlist?.items ?? []).some((item) => allIds.includes(item.empresa_id));
  const toggleWatch = useMutation({
    mutationFn: () =>
      Promise.all(
        allIds.map((id) =>
          watched
            ? apiMutate("DELETE", `/api/v1/competitive/watchlist/${id}`)
            : apiMutate("POST", "/api/v1/competitive/watchlist", {
                empresa_id: id,
                frequency: "daily",
              }),
        ),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["watchlist-empresas"] }),
  });

  if (isLoading) return <ProfileSkeleton />;

  if (error || !profile) {
    return (
      <Card className="border-destructive/30 mx-auto max-w-2xl">
        <CardContent className="p-8 text-center">
          <ShieldAlert className="text-destructive mx-auto h-8 w-8" aria-hidden="true" />
          <h1 className="mt-4 text-xl font-semibold">No se pudo abrir el perfil</h1>
          <p className="text-muted-foreground mt-2 text-sm">
            La empresa no existe o el servicio no está disponible ahora mismo.
          </p>
          <Link href="/competidores" className="text-primary mt-5 inline-flex text-sm font-medium hover:underline">
            Volver a competidores
          </Link>
        </CardContent>
      </Card>
    );
  }

  const totals = profile.totales;
  const noActivity = totals.contratos === 0;
  const periodOptions: { value: Period; label: string }[] = [
    { value: "12m", label: "12 meses" },
    { value: "3y", label: "3 años" },
    { value: "all", label: "Todo" },
  ];
  if (hasGlobalPeriod) periodOptions.unshift({ value: "global", label: "Filtro global" });

  return (
    <div className="space-y-6 pb-12">
      <section className="bg-card rounded-xl border">
        <div className="p-5 md:p-7">
          <Link
            href="/competidores"
            className="text-muted-foreground hover:text-foreground inline-flex min-h-9 items-center gap-2 text-sm font-medium"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Volver al mercado
          </Link>
          <div className="mt-5 flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                {profile.empresa.nif ? <Badge variant="outline">NIF {profile.empresa.nif}</Badge> : null}
                {profile.empresa.es_ute ? <Badge variant="info">UTE</Badge> : null}
                {profile.empresa.grupo ? <Badge variant="secondary">Grupo {profile.empresa.grupo}</Badge> : null}
              </div>
              <h1 className="mt-3 max-w-4xl text-2xl font-semibold tracking-tight md:text-3xl">
                {profile.empresa.nombre}
              </h1>
              <div className="text-muted-foreground mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
                <span className="inline-flex items-center gap-1.5">
                  <CalendarDays className="h-4 w-4" aria-hidden="true" />
                  Trayectoria: {formatDate(profile.actividad_historica.primera_adjudicacion)} —{" "}
                  {formatDate(profile.actividad_historica.ultima_adjudicacion)}
                </span>
                <span>{formatNumber(profile.actividad_historica.contratos)} adjudicaciones históricas</span>
                <span className="inline-flex items-center gap-1.5">
                  <Building2 className="h-4 w-4" aria-hidden="true" />
                  {formatNumber(profile.totales.organos)} clientes públicos en el periodo
                </span>
              </div>
            </div>
            <Button
              variant={watched ? "secondary" : "outline"}
              className="min-h-10 shrink-0"
              onClick={() => toggleWatch.mutate()}
              disabled={toggleWatch.isPending}
            >
              {watched ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
              {watched ? "Dejar de vigilar" : "Vigilar empresa"}
            </Button>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-2 border-t pt-5">
            <span className="text-muted-foreground mr-1 text-xs font-semibold tracking-[0.14em] uppercase">
              Periodo
            </span>
            {periodOptions.map((option) => (
              <Button
                key={option.value}
                variant={period === option.value ? "default" : "outline"}
                size="sm"
                className="min-h-9"
                onClick={() => setPeriod(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>
      </section>

      {noActivity ? (
        <div className="bg-muted/20 rounded-lg border border-dashed p-6 text-center">
          <p className="font-medium">Sin adjudicaciones dentro de este ámbito</p>
          <p className="text-muted-foreground mt-1 text-sm">
            La empresa existe, pero no tiene actividad que cumpla el periodo y los filtros seleccionados.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          <CompanyProfileSummary profile={profile} />
          <section aria-labelledby="company-awards-section-title">
            <h2 id="company-awards-section-title" className="sr-only">
              Listado de adjudicaciones
            </h2>
            <CompanyAwards empresaId={empresaId} scopeQuery={scopeQuery} />
          </section>
        </div>
      )}
    </div>
  );
}
