"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, CalendarDays, ShieldAlert } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { SeguirBoton } from "@/components/seguir-boton";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import { useFilters } from "@/lib/filters";
import { cn, formatDate, formatNumber } from "@/lib/utils";

import { PanelTabs } from "@/components/console/panel";
import { registrarEvento } from "@/lib/analytics";

import { CompanyAwards } from "./company-awards";
import { CompanyContraMi } from "./company-contra-mi";
import { CompanyProfileSummary } from "./company-profile-summary";
import { CompanyUteParticipations } from "./company-ute-participations";
import type { CompanyProfileData } from "./company-profile-types";
import { competitiveKeys } from "@/lib/query-keys";

// La identidad no se ve al entrar —es una pestaña— y esta ruta va justa de
// presupuesto de First Load (`web/bundle-budget.json`): se carga al abrirla.
const CompanyIdentidad = dynamic(
  () => import("./company-identidad").then((modulo) => modulo.CompanyIdentidad),
  { loading: () => <Skeleton className="h-48 w-full rounded-lg" /> },
);

type Period = "12m" | "3y" | "all" | "global";

/**
 * Pestañas del dossier. «Contra mí» (F3.2) es la única que habla de nosotros:
 * cruza las oportunidades presentadas del equipo con las adjudicaciones de
 * esta empresa. La clave del competidor es su id del maestro, que es lo primero
 * que prueba `empresa_key_sql` en el backend. «Identidad» es quién es la
 * empresa en el maestro —NIF, alias, UTE y, si la ficha suma varias, cuáles—,
 * y no depende de ningún filtro.
 */
type Pestana = "perfil" | "identidad" | "contra_mi";

/**
 * Alcance del dossier, en la URL (`?alcance=historico`) para poder enlazarlo.
 *
 * Por defecto la ficha aplica el ámbito global —CCAA, tecnología e importe de
 * la barra— y el periodo elegido. «Todo el histórico» no aplica ni lo uno ni
 * lo otro: es la actividad entera de la empresa, la cifra que enseñaba la ficha
 * de `/empresas`. Hasta 2026-09-24 no había forma de verla aquí: «Todo» sólo
 * quitaba las fechas y los demás filtros seguían aplicando.
 */
const ALCANCES = ["historico"] as const;

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
  const [alcance, setAlcance] = useQueryState("alcance", parseAsStringLiteral(ALCANCES));
  const historico = alcance === "historico";
  const [pestana, setPestana] = useState<Pestana>("perfil");
  const cambiarPestana = (siguiente: Pestana) => {
    setPestana(siguiente);
    if (siguiente !== "perfil") {
      registrarEvento("espacio_abierto", { espacio: "competencia", origen: "conmutador", vista: siguiente });
    }
  };
  // El dossier agrega la actividad de todo el grupo; el usuario nunca elige
  // cuál identidad abrir.
  const allIds = useMemo(() => [...new Set([empresaId, ...(groupIds ?? [])])], [empresaId, groupIds]);

  const scopeQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (allIds.length > 1) params.set("empresa_ids", allIds.join(","));
    // Todo el histórico: ni ámbito ni fechas, la actividad entera del grupo.
    if (historico) return params.toString();
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
  }, [
    allIds,
    historico,
    filters.ccaas,
    filters.importeMin,
    filters.rango.desde,
    filters.rango.hasta,
    filters.tecnologias,
    period,
  ]);

  const {
    data: profile,
    isLoading,
    isPlaceholderData,
    error,
  } = useQuery<CompanyProfileData>({
    queryKey: competitiveKeys.companyProfile(empresaId, scopeQuery),
    queryFn: () =>
      fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/perfil${scopeQuery ? `?${scopeQuery}` : ""}`),
    staleTime: 5 * 60 * 1000,
    // Cambiar de alcance o de periodo deja la ficha anterior, atenuada, hasta
    // que llega la nueva. Antes volvía al esqueleto de página entera, que se
    // llevaba también los botones recién pulsados. Sólo si es la misma
    // empresa: al saltar a otra (un socio de UTE), su nombre no puede ir
    // encima de las cifras de la anterior.
    placeholderData: (previo, consultaPrevia) => (consultaPrevia?.queryKey[1] === empresaId ? previo : undefined),
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
          <Link
            href="/competencia?vista=competidores"
            className="text-primary mt-5 inline-flex text-sm font-medium hover:underline"
          >
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
            href="/competencia?vista=competidores"
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
            {/* El control único de ADR-031 §C; sigue el grupo de identidades. */}
            <SeguirBoton
              targetType="empresa"
              targetId={String(empresaId)}
              equivalentes={allIds.map(String)}
              icono="ojo"
              nombreAccesible="visible"
              textos={{ seguir: "Vigilar empresa", siguiendo: "Dejar de vigilar" }}
              clases={{
                base: "min-h-10 shrink-0",
                activo: buttonVariants({ variant: "secondary" }),
                inactivo: buttonVariants({ variant: "outline" }),
              }}
            />
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-3 border-t pt-5">
            <div role="group" aria-label="Alcance" className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground mr-1 text-xs font-semibold tracking-[0.14em] uppercase">
                Alcance
              </span>
              <Button
                variant={historico ? "outline" : "default"}
                size="sm"
                className="min-h-9"
                aria-pressed={!historico}
                onClick={() => void setAlcance(null)}
              >
                Tu ámbito
              </Button>
              <Button
                variant={historico ? "default" : "outline"}
                size="sm"
                className="min-h-9"
                aria-pressed={historico}
                onClick={() => void setAlcance("historico")}
              >
                Todo el histórico
              </Button>
            </div>
            {/* El periodo sólo acota «Tu ámbito»: el histórico no tiene fechas. */}
            {!historico && (
              <div role="group" aria-label="Periodo" className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground mr-1 text-xs font-semibold tracking-[0.14em] uppercase">
                  Periodo
                </span>
                {periodOptions.map((option) => (
                  <Button
                    key={option.value}
                    variant={period === option.value ? "default" : "outline"}
                    size="sm"
                    className="min-h-9"
                    aria-pressed={period === option.value}
                    onClick={() => setPeriod(option.value)}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            )}
          </div>
          {historico && (
            // La barra de ámbito sigue mostrando sus filtros; esta ficha los
            // ignora, y tiene que decirlo donde se miran las cifras.
            <p className="text-muted-foreground mt-3 text-sm">
              Toda la actividad de la empresa, sin los filtros del ámbito ni fechas.
            </p>
          )}
        </div>
      </section>

      <PanelTabs
        label="Secciones del dossier"
        value={pestana}
        onChange={cambiarPestana}
        tabs={[
          { key: "perfil", label: "Perfil" },
          { key: "identidad", label: "Identidad" },
          { key: "contra_mi", label: "Contra mí" },
        ]}
      />

      {pestana === "contra_mi" ? (
        <CompanyContraMi empresaKey={String(empresaId)} />
      ) : pestana === "identidad" ? (
        <CompanyIdentidad empresaIds={allIds} />
      ) : (
        <div
          aria-busy={isPlaceholderData}
          className={cn("transition-opacity duration-150", isPlaceholderData && "opacity-60")}
        >
          {noActivity ? (
            // Un miembro que solo ha ganado a través de UTEs tiene 0
            // adjudicaciones propias: sin esta rama su participación quedaría
            // igual de invisible que antes de exponerla.
            <div className="space-y-6">
              <div className="bg-muted/20 rounded-lg border border-dashed p-6 text-center">
                {historico ? (
                  <>
                    <p className="font-medium">Sin adjudicaciones propias</p>
                    <p className="text-muted-foreground mt-1 text-sm">
                      La empresa está en el maestro, pero no ha ganado nada a su nombre. Si ha ganado en UTE, aparece
                      debajo.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="font-medium">Sin adjudicaciones dentro de este ámbito</p>
                    <p className="text-muted-foreground mt-1 text-sm">
                      La empresa existe, pero no tiene actividad que cumpla el periodo y los filtros seleccionados.
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-4 min-h-9"
                      onClick={() => void setAlcance("historico")}
                    >
                      Ver todo el histórico
                    </Button>
                  </>
                )}
              </div>
              <CompanyUteParticipations
                participations={profile.participaciones_ute}
                companyName={profile.empresa.nombre}
              />
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
      )}
    </div>
  );
}
