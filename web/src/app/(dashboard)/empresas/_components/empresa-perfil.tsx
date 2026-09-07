"use client";

import * as React from "react";
import { Star, TrendingDown, TrendingUp } from "lucide-react";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { EmpresaDetail, PerfilEmpresa } from "../_hooks/use-maestro";

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

function Separador({ text }: { text: string }) {
  return (
    <>
      <span className="text-muted-foreground/60">·</span>
      <span>{text}</span>
    </>
  );
}

function SubTitulo({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center gap-2.5">
      <h3 className="text-tf-micro text-muted-foreground font-mono font-semibold tracking-[0.1em] uppercase">
        {children}
      </h3>
      {aside}
    </div>
  );
}

function Total({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="border-border/60 min-w-0 rounded-[10px] border px-3.5 py-3">
      <div className="text-tf-meta text-muted-foreground mb-2.5">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className="tf-tnum text-tf-title font-mono font-semibold">{value}</span>
        {sub && <span className="text-tf-meta text-muted-foreground">{sub}</span>}
      </div>
    </div>
  );
}

/**
 * Trayectoria por año: la altura es el importe, la cifra son los contratos.
 *
 * A 120px de alto y con la cifra a 11px se lee; a 92 con la cifra a 9,5 no.
 * Y el año va completo (2021, no «21»): abreviarlo no ahorraba ni el ancho de
 * una barra.
 */
function Trayectoria({ anios }: { anios: { anio: number; contratos: number; importe: number }[] }) {
  const maximo = Math.max(...anios.map((a) => a.importe), 1);
  const primero = anios[0]?.importe ?? 0;
  const ultimoCompleto = anios[Math.max(0, anios.length - 2)]?.importe ?? 0;
  const creciendo = ultimoCompleto >= primero;
  const Icono = creciendo ? TrendingUp : TrendingDown;

  return (
    <>
      <SubTitulo
        aside={
          <>
            <span
              className={cn(
                "text-tf-meta inline-flex items-center gap-1.5 font-medium",
                creciendo ? "text-[hsl(var(--success))]" : "text-destructive",
              )}
            >
              <Icono className="h-3 w-3" aria-hidden="true" />
              {creciendo ? "en crecimiento" : "en declive"}
            </span>
            <span className="flex-1" />
          </>
        }
      >
        Trayectoria por año
      </SubTitulo>
      <div className="border-border/60 relative mb-6 flex h-[120px] items-end gap-2.5 border-b pb-5">
        {anios.map((anio) => (
          <div key={anio.anio} className="relative flex h-full flex-1 flex-col items-center justify-end gap-1.5">
            <span className="tf-tnum text-tf-micro text-muted-foreground font-mono font-medium">
              {formatNumber(anio.contratos)}
            </span>
            <span
              className="bg-primary/70 block min-h-[2px] w-full rounded-t-[3px]"
              style={{ height: `${(anio.importe / maximo) * 100}%` }}
              title={`${anio.anio}: ${formatNumber(anio.contratos)} contratos · ${formatCurrency(anio.importe)}`}
            />
            <span className="text-tf-micro text-muted-foreground absolute -bottom-[18px] font-mono">{anio.anio}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function Ranking({
  title,
  rows,
  className,
}: {
  title: string;
  rows: { label: string; contratos: number; importe: number }[];
  className?: string;
}) {
  const maximo = Math.max(...rows.map((r) => r.contratos), 1);
  return (
    <div className={cn("min-w-0", className)}>
      <SubTitulo>{title}</SubTitulo>
      {rows.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">Sin datos.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.slice(0, 6).map((row) => (
            <div key={row.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
              <span className="flex min-w-0 items-center gap-2.5">
                <span
                  className="bg-primary/55 h-1 flex-none rounded-sm"
                  style={{ width: `${Math.max(4, (row.contratos / maximo) * 40)}px` }}
                />
                <span className="text-tf-body text-muted-foreground min-w-0 truncate">{row.label}</span>
              </span>
              <span className="tf-tnum text-tf-meta text-muted-foreground font-mono font-medium whitespace-nowrap">
                {formatNumber(row.contratos)} · {formatCurrency(row.importe)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Relacionadas({
  title,
  items,
  onOpen,
}: {
  title: string;
  items: { empresa_id: number; nombre_canonico: string }[];
  onOpen: (empresaId: number) => void;
}) {
  return (
    <div className="min-w-0">
      <SubTitulo>{title}</SubTitulo>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <button
            key={item.empresa_id}
            type="button"
            onClick={() => onOpen(item.empresa_id)}
            className="tf-pressable border-border/70 text-tf-meta text-foreground hover:border-primary/50 inline-flex h-6.5 items-center rounded-md border px-2.5 font-medium transition-colors"
          >
            {item.nombre_canonico}
          </button>
        ))}
      </div>
    </div>
  );
}
