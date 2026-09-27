"use client";

/**
 * Ficha del maestro: quién es la empresa, no cómo compite.
 *
 * Hasta 2026-09-25 repetía el perfil competitivo —totales, trayectoria y
 * rankings por CPV, territorio y órgano— con cifras que no cuadraban con las de
 * Competencia, porque allí se aplica el ámbito y se suman las identidades del
 * grupo. Ese análisis ya vive en una sola ficha, la de Competencia. Aquí quedan
 * la identidad, una línea de actividad y la puerta a esa ficha, que se abre en
 * «Todo el histórico» para enseñar las mismas cifras que esta línea.
 */

import * as React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cn, formatCurrency, formatMonth, formatNumber } from "@/lib/utils";
import { PanelError, SectionTitle } from "@/components/console/panel";
import { SeguirBoton } from "@/components/seguir-boton";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { EmpresaDetail, PerfilEmpresa } from "../_hooks/use-maestro";
import { Relacionadas, Separador } from "./empresa-perfil-piezas";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export interface EmpresaPerfilProps {
  detail: EmpresaDetail | undefined;
  perfil: PerfilEmpresa | undefined;
  /** El perfil aún no ha llegado. Sin perfil y sin carga, es que falló. */
  perfilCargando: boolean;
  loading: boolean;
  /** El fallo de la identidad de la empresa: se dice, no se queda en esqueleto. */
  error?: unknown;
  onRetry?: () => void;
  /**
   * Tras vigilar o dejar de vigilar, con el estado nuevo. El cambio lo hace
   * `SeguirBoton`; esto es sólo para que la pantalla avise.
   */
  onWatchToggled?: (ahoraVigila: boolean) => void;
  /** Filtra el maestro por el grupo empresarial de la ficha. */
  onOpenGrupo: (grupo: string) => void;
  /** Salta a otra empresa del maestro por su id (miembros de UTE, UTEs). */
  onOpenEmpresa: (empresaId: number) => void;
}

export function EmpresaPerfil({
  detail,
  perfil,
  perfilCargando,
  loading,
  error,
  onRetry,
  onWatchToggled,
  onOpenGrupo,
  onOpenEmpresa,
}: EmpresaPerfilProps) {
  if (!loading && !detail && error) {
    return (
      <div className="px-5 py-4">
        <PanelError title="No se pudo abrir la empresa" error={error} onRetry={onRetry} />
      </div>
    );
  }

  if (loading || !detail) {
    // El esqueleto también en la carga global. Antes sólo aparecía al cambiar
    // de fila: mientras cargaba la pantalla entera, este panel decía «ninguna
    // empresa seleccionada», que es un vacío, no una espera.
    return (
      <div className="flex flex-1 flex-col gap-3 px-5 py-4">
        {[72, 64, 120].map((height) => (
          <Skeleton key={height} className="w-full rounded-xl" style={{ height }} />
        ))}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-border/60 flex-none border-b px-5 py-4">
        <div className="mb-1.5 flex items-center gap-2.5">
          <h2 className="font-display text-tf-title font-semibold">{detail.nombre_canonico}</h2>
          <div className="flex-1" />
          {/* El control único de ADR-031 §C, el mismo de la fila del maestro
              y del dossier de Competencia, con la piel de esta cabecera. */}
          <SeguirBoton
            targetType="empresa"
            targetId={String(detail.empresa_id)}
            icono="estrella"
            nombreAccesible="visible"
            textos={{ seguir: "Vigilar", siguiendo: "En vigilancia" }}
            clases={{
              base: "tf-pressable text-tf-meta inline-flex h-8 flex-none items-center gap-1.5 rounded-md border px-2.5 font-medium md:h-7",
              activo: "border-primary/30 bg-primary/10 text-primary",
              inactivo: "border-border/70 text-foreground hover:border-primary/50",
              icono: "h-3 w-3",
            }}
            onAlternar={onWatchToggled}
          />
        </div>
        {/* Identidad en una línea de texto neutro: NIF y marcas. El grupo es lo
            único que lleva a algún sitio, así que es lo único que se pinta
            como enlace. */}
        <div className="text-tf-meta text-muted-foreground flex flex-wrap items-center gap-2">
          <span className={cn(detail.nif_canonico && "font-mono")}>{detail.nif_canonico ?? "Sin NIF canónico"}</span>
          {detail.es_ute ? <Separador text="UTE" /> : null}
          {detail.es_pyme ? <Separador text="PYME" /> : null}
          {detail.grupo && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => onOpenGrupo(detail.grupo!)}
                    className="text-tf-meta text-primary font-medium hover:underline"
                  >
                    Grupo {detail.grupo}
                  </button>
                </TooltipTrigger>
                <TooltipContent>Filtrar el maestro por grupo</TooltipContent>
              </Tooltip>
            </>
          )}
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-y-auto px-5 pt-4 pb-6">
        <Actividad empresaId={detail.empresa_id} perfil={perfil} cargando={perfilCargando} />

        <div className="grid grid-cols-2 gap-x-6 gap-y-4">
          {detail.ute_miembros.length > 0 && (
            <Relacionadas title="Miembros de la UTE" items={detail.ute_miembros} onOpen={onOpenEmpresa} />
          )}
          {detail.participa_en_utes.length > 0 && (
            <Relacionadas title="Participa en UTEs" items={detail.participa_en_utes} onOpen={onOpenEmpresa} />
          )}
          {detail.aliases.length > 1 && (
            <div className="col-span-2 min-w-0">
              <SectionTitle as="h3">Alias vistos en fuente ({detail.aliases.length})</SectionTitle>
              <div className="flex flex-wrap items-center gap-1.5">
                {detail.aliases.slice(0, 12).map((alias, i) => (
                  <span
                    key={`${alias.alias_normalizado}-${i}`}
                    className="bg-muted text-tf-meta text-muted-foreground inline-flex h-6 items-center rounded-md px-2"
                  >
                    {alias.alias_normalizado}
                  </span>
                ))}
                {detail.aliases.length > 12 && (
                  <span className="text-tf-meta text-muted-foreground">+{detail.aliases.length - 12} más</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Una línea de actividad y la puerta a la ficha de Competencia.
 *
 * El enlace no depende del perfil: si el perfil falla, la ficha sigue siendo
 * el sitio donde ver la actividad, así que se ofrece igual.
 */
function Actividad({
  empresaId,
  perfil,
  cargando,
}: {
  empresaId: number;
  perfil: PerfilEmpresa | undefined;
  cargando: boolean;
}) {
  const totales = perfil?.totales;
  return (
    <div className="border-border/60 mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border px-3.5 py-3">
      <div className="min-w-0 flex-1">
        <SectionTitle as="h3">Actividad en todo el histórico</SectionTitle>
        {cargando ? (
          <Skeleton className="h-5 w-64 max-w-full" />
        ) : !totales ? (
          <p className="text-tf-body text-muted-foreground">No se pudo cargar la actividad.</p>
        ) : totales.contratos === 0 ? (
          <p className="text-tf-body text-muted-foreground">Sin adjudicaciones propias.</p>
        ) : (
          <p className="tf-tnum text-tf-body text-foreground">
            {formatNumber(totales.contratos)} {totales.contratos === 1 ? "contrato" : "contratos"} ·{" "}
            {formatCurrency(totales.importe_total)}
            {totales.primera_adjudicacion && (
              <span className="text-muted-foreground">
                {" "}
                · activa {formatMonth(totales.primera_adjudicacion.slice(0, 7), true)} →{" "}
                {totales.ultima_adjudicacion ? formatMonth(totales.ultima_adjudicacion.slice(0, 7), true) : "hoy"}
              </span>
            )}
          </p>
        )}
      </div>
      <Link
        href={`/competencia/empresa/${empresaId}?alcance=historico`}
        className={buttonVariants({ variant: "outline", size: "sm", className: "flex-none" })}
      >
        Abrir ficha
        <ArrowRight aria-hidden="true" />
      </Link>
    </div>
  );
}
