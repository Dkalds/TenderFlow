"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { SeguirBoton } from "@/components/seguir-boton";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import { useFilters } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatDate, formatNumber } from "@/lib/utils";

import {
  EnlaceIr,
  Panel,
  PanelEmpty,
  PanelError,
  PanelTabs,
  ROTULO_DATO,
  SUPERFICIE_PANEL,
  Segmented,
  panelDePestana,
} from "@/components/console/panel";
import { registrarEvento } from "@/lib/analytics";

import { ProfileSkeleton } from "./company-profile-esqueleto";

import { CompanyAwards } from "./company-awards";
import { CompanyProfileSummary } from "./company-profile-summary";
import { CompanyUteParticipations } from "./company-ute-participations";
import type { CompanyProfileData } from "./company-profile-types";
import { competitiveKeys } from "@/lib/query-keys";

// «Identidad» y «Contra mí» son pestañas: no se ven al entrar, y esta ruta va
// justa de presupuesto de First Load (`web/bundle-budget.json`). Se cargan al
// abrirlas, como el inspector de /detalle.
const pestanaCargando = () => <Skeleton className="h-48 w-full rounded-xl" />;
const CompanyIdentidad = dynamic(
  () => import("./company-identidad").then((modulo) => modulo.CompanyIdentidad),
  { loading: pestanaCargando },
);
const CompanyContraMi = dynamic(
  () => import("./company-contra-mi").then((modulo) => modulo.CompanyContraMi),
  { loading: pestanaCargando },
);

type Period = "12m" | "3y" | "all" | "global";

/**
 * Pestañas del dossier. «Contra mí» (F3.2) es la única que habla de nosotros:
 * cruza las oportunidades presentadas del equipo con las adjudicaciones de
 * esta empresa. La clave del competidor es su id del maestro, que es lo primero
 * que prueba `empresa_key_sql` en el backend, y cruza también las del grupo,
 * como el perfil. «Identidad» es quién es la
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

const ID_PESTANAS = "dossier-empresa";

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
    refetch,
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
    // El fallo se dice en la propia ficha (PanelError): sin toast además.
    meta: META_ERROR_EN_LINEA,
  });

  if (isLoading) return <ProfileSkeleton />;

  if (error || !profile) {
    return (
      <div className="mx-auto max-w-2xl space-y-3">
        <h1 className="sr-only">Ficha de empresa</h1>
        <PanelError
          title="No se pudo abrir el perfil"
          error={error ?? undefined}
          message={error ? undefined : "La empresa no existe o ya no está disponible."}
          onRetry={error ? () => void refetch() : undefined}
        />
        <EnlaceIr href="/competencia?vista=competidores">Volver a competidores</EnlaceIr>
      </div>
    );
  }

  const totals = profile.totales;
  const noActivity = totals.contratos === 0;
  const alcanceOptions: { value: "ambito" | "historico"; label: string }[] = [
    { value: "ambito", label: "Tu ámbito" },
    { value: "historico", label: "Todo el histórico" },
  ];
  const periodOptions: { value: Period; label: string }[] = [
    { value: "12m", label: "12 meses" },
    { value: "3y", label: "3 años" },
    { value: "all", label: "Todo" },
  ];
  if (hasGlobalPeriod) periodOptions.unshift({ value: "global", label: "Filtro global" });

  return (
    <div className="space-y-6 pb-12">
      <section className={SUPERFICIE_PANEL}>
        <div className="p-5 md:p-6">
          <Link
            href="/competencia?vista=competidores"
            className="inline-flex min-h-9 items-center gap-1.5 text-tf-meta font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Volver al mercado
          </Link>
          <div className="mt-4 flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                {profile.empresa.nif ? (
                  <Badge variant="outline">
                    NIF <span className="font-mono">{profile.empresa.nif}</span>
                  </Badge>
                ) : null}
                {profile.empresa.es_ute ? <Badge variant="info">UTE</Badge> : null}
                {profile.empresa.grupo ? <Badge variant="secondary">Grupo {profile.empresa.grupo}</Badge> : null}
              </div>
              <h1 className="mt-3 max-w-4xl font-display text-tf-title">{profile.empresa.nombre}</h1>
              <p className="mt-2 flex flex-wrap gap-x-1.5 gap-y-1 text-tf-meta text-muted-foreground">
                <span>
                  Trayectoria: {formatDate(profile.actividad_historica.primera_adjudicacion)} –{" "}
                  {formatDate(profile.actividad_historica.ultima_adjudicacion)}
                </span>
                <span aria-hidden="true">·</span>
                <span>{formatNumber(profile.actividad_historica.contratos)} adjudicaciones históricas</span>
                <span aria-hidden="true">·</span>
                <span>{formatNumber(profile.totales.organos)} clientes públicos en el periodo</span>
              </p>
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
                base: "shrink-0",
                activo: buttonVariants({ variant: "secondary", size: "sm" }),
                inactivo: buttonVariants({ variant: "outline", size: "sm" }),
              }}
            />
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-border/60 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={ROTULO_DATO} aria-hidden="true">
                Alcance
              </span>
              <Segmented
                aria-label="Alcance"
                value={historico ? "historico" : "ambito"}
                onChange={(siguiente) => void setAlcance(siguiente === "historico" ? "historico" : null)}
                options={alcanceOptions}
              />
            </div>
            {/* El periodo sólo acota «Tu ámbito»: el histórico no tiene fechas. */}
            {!historico && (
              <div className="flex flex-wrap items-center gap-2">
                <span className={ROTULO_DATO} aria-hidden="true">
                  Periodo
                </span>
                <Segmented aria-label="Periodo" value={period} onChange={setPeriod} options={periodOptions} />
              </div>
            )}
          </div>
          {historico && (
            // La barra de ámbito sigue mostrando sus filtros; esta ficha los
            // ignora, y tiene que decirlo donde se miran las cifras.
            <p className="mt-3 text-tf-meta text-muted-foreground">
              Toda la actividad de la empresa, sin los filtros del ámbito ni fechas.
            </p>
          )}
        </div>
      </section>

      <PanelTabs
        label="Secciones del dossier"
        value={pestana}
        onChange={cambiarPestana}
        idBase={ID_PESTANAS}
        tabs={[
          { key: "perfil", label: "Perfil" },
          { key: "identidad", label: "Identidad" },
          { key: "contra_mi", label: "Contra mí" },
        ]}
      />

      <div className="focus-visible:outline-none" {...panelDePestana(ID_PESTANAS, pestana)}>
        {pestana === "contra_mi" ? (
          <CompanyContraMi empresaKey={String(empresaId)} empresaIds={allIds} />
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
                <Panel>
                  {historico ? (
                    <PanelEmpty
                      title="Sin adjudicaciones propias"
                      hint="La empresa está en el maestro, pero no ha ganado nada a su nombre. Si ha ganado en UTE, aparece debajo."
                    />
                  ) : (
                    <PanelEmpty
                      title="Sin adjudicaciones dentro de este ámbito"
                      hint="La empresa existe, pero no tiene actividad que cumpla el periodo y los filtros seleccionados."
                      action={
                        <Button variant="outline" size="sm" onClick={() => void setAlcance("historico")}>
                          Ver todo el histórico
                        </Button>
                      }
                    />
                  )}
                </Panel>
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
    </div>
  );
}
