"use client";

import * as React from "react";
import { Star } from "lucide-react";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { EmpresaDetail, PerfilEmpresa } from "../_hooks/use-maestro";
import { Ranking, Relacionadas, Separador, SubTitulo, Total, Trayectoria } from "./empresa-perfil-piezas";

export interface EmpresaPerfilProps {
  detail: EmpresaDetail | undefined;
  perfil: PerfilEmpresa | undefined;
  loading: boolean;
  watched: boolean;
  onToggleWatch: () => void;
  /** Hay un alta o baja de vigilancia en vuelo: no se aceptan más clics. */
  watchPending: boolean;
  /** Filtra el maestro por el grupo empresarial de la ficha. */
  onOpenGrupo: (grupo: string) => void;
  /** Salta a otra empresa del maestro por su id (miembros de UTE, UTEs). */
  onOpenEmpresa: (empresaId: number) => void;
}

export function EmpresaPerfil({
  detail,
  perfil,
  loading,
  watched,
  onToggleWatch,
  watchPending,
  onOpenGrupo,
  onOpenEmpresa,
}: EmpresaPerfilProps) {
  if (loading || !detail) {
    // El esqueleto también en la carga global. Antes sólo aparecía al cambiar
    // de fila: mientras cargaba la pantalla entera, este panel decía «ninguna
    // empresa seleccionada», que es un vacío, no una espera.
    return (
      <div className="flex flex-1 flex-col gap-3 px-5 py-4">
        {[72, 64, 120, 140].map((height) => (
          <Skeleton key={height} className="w-full rounded-[10px]" style={{ height }} />
        ))}
      </div>
    );
  }

  const totales = perfil?.totales;
  const anios = [...(perfil?.por_anio ?? [])].sort((a, b) => a.anio - b.anio);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-border/60 flex-none border-b px-5 py-4">
        <div className="mb-1.5 flex items-center gap-2.5">
          <h2 className="font-display text-tf-title font-semibold tracking-[-0.01em]">{detail.nombre_canonico}</h2>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onToggleWatch}
            disabled={watchPending}
            aria-pressed={watched}
            className={cn(
              "tf-pressable text-tf-meta inline-flex h-[30px] flex-none items-center gap-1.5 rounded-md border px-3 font-medium transition-colors duration-140 ease-out",
              watched
                ? "border-primary/50 bg-primary/12 text-primary"
                : "border-border/70 text-foreground hover:border-primary/40",
            )}
          >
            <Star className="h-3 w-3" fill={watched ? "currentColor" : "none"} aria-hidden="true" />
            {watched ? "En vigilancia" : "Vigilar"}
          </button>
        </div>
        {/* Identidad en una línea de texto neutro: NIF, marcas y ventana de
            actividad. El grupo es lo único que lleva a algún sitio, así que es
            lo único que se pinta como enlace. */}
        <div className="text-tf-meta text-muted-foreground flex flex-wrap items-center gap-2 font-mono">
          <span>{detail.nif_canonico ?? "Sin NIF canónico"}</span>
          {detail.es_ute ? <Separador text="UTE" /> : null}
          {detail.es_pyme ? <Separador text="PYME" /> : null}
          {detail.grupo && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <button
                type="button"
                onClick={() => onOpenGrupo(detail.grupo!)}
                title="Filtrar el maestro por grupo"
                className="text-tf-meta text-primary font-sans font-medium hover:underline"
              >
                Grupo {detail.grupo}
              </button>
            </>
          )}
          {totales?.primera_adjudicacion && (
            <>
              <span className="text-muted-foreground/60">·</span>
              <span>
                activa {totales.primera_adjudicacion.slice(0, 7)} → {totales.ultima_adjudicacion?.slice(0, 7) ?? "hoy"}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pt-4 pb-6">
        <div className="mb-6 grid grid-cols-3 gap-3">
          <Total label="Contratos adjudicados" value={formatNumber(totales?.contratos ?? 0)} />
          <Total
            label="Importe adjudicado"
            value={formatCurrency(totales?.importe_total)}
            sub={
              totales && totales.contratos > 0
                ? `${formatCurrency(totales.importe_total / totales.contratos)} de media`
                : undefined
            }
          />
          <Total
            label="Ofertas medias por licitación"
            value={totales?.ofertas_medias != null ? totales.ofertas_medias.toFixed(1).replace(".", ",") : "—"}
            sub="presión competitiva"
          />
        </div>

        {anios.length > 0 && <Trayectoria anios={anios} />}

        {/* Dos rankings arriba y los órganos a ancho completo debajo: el
            nombre de un órgano no cabe en un tercio de panel, y por eso el
            código anterior lo cortaba a mano a 38 caracteres. */}
        <div className="mb-6 grid grid-cols-2 gap-x-6 gap-y-3">
          <Ranking
            title="Por familia CPV"
            rows={(perfil?.por_cpv ?? []).map((r) => ({
              label: `CPV ${r.cpv2}`,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
          <Ranking
            title="Por territorio"
            rows={(perfil?.por_ccaa ?? []).map((r) => ({
              label: r.ccaa,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
          <Ranking
            className="col-span-2"
            title="Órganos principales"
            rows={(perfil?.organos_principales ?? []).map((r) => ({
              label: r.organo,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-4">
          {detail.ute_miembros.length > 0 && (
            <Relacionadas title="Miembros de la UTE" items={detail.ute_miembros} onOpen={onOpenEmpresa} />
          )}
          {detail.participa_en_utes.length > 0 && (
            <Relacionadas title="Participa en UTEs" items={detail.participa_en_utes} onOpen={onOpenEmpresa} />
          )}
          {detail.aliases.length > 1 && (
            <div className="col-span-2 min-w-0">
              <SubTitulo>Aliases vistos en fuente ({detail.aliases.length})</SubTitulo>
              <div className="flex flex-wrap items-center gap-1.5">
                {detail.aliases.slice(0, 12).map((alias, i) => (
                  <span
                    key={`${alias.alias_normalizado}-${i}`}
                    className="bg-muted-foreground/8 text-tf-meta text-muted-foreground inline-flex h-6 items-center rounded px-2 font-mono"
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
