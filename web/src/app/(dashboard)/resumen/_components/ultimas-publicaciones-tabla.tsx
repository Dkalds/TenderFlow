"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { IndicadorOrden } from "@/components/ui/data-table";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { CHART_SERIES } from "@/lib/chart-colors";
import { fuenteOrigen } from "@/lib/fuentes";
import { EMPTY, cn, formatCompactCurrency, formatCurrency } from "@/lib/utils";
import { esNueva, type TimelineItem } from "./types";
import {
  COLUMNAS,
  anchoImporte,
  fechaPublicacionCorta,
  type DireccionOrden,
} from "./ultimas-publicaciones-data";

/** Punto de «nueva desde tu última visita», con su texto para el lector. */
function PuntoNueva({ nueva }: { nueva: boolean }) {
  if (!nueva) return <span className="h-1.5 w-1.5 flex-none" aria-hidden="true" />;
  return (
    <>
      <span className="h-1.5 w-1.5 flex-none rounded-full bg-primary" aria-hidden="true" />
      <span className="sr-only">Nueva desde tu última visita.</span>
    </>
  );
}

/**
 * Barra del importe. SVG con atributos y no un ancho en un estilo en línea: el
 * ancho cambia por fila y un estilo en línea más alejaría el día en que
 * `style-src` deje de llevar `'unsafe-inline'` (scripts/check_inline_styles.py).
 */
function BarraImporte({ importe }: { importe: number | null }) {
  const ancho = anchoImporte(importe);
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 4"
      preserveAspectRatio="none"
      className="h-1 w-12 flex-none overflow-hidden rounded-full"
    >
      <rect width="100" height="4" className="fill-border/40" />
      {ancho > 0 && <rect width={ancho} height="4" fill={CHART_SERIES[0]} />}
    </svg>
  );
}

function CeldaOrigen({ fuente }: { fuente: string | null | undefined }) {
  const origen = fuenteOrigen(fuente);
  if (!origen) return <span className="text-tf-micro text-muted-foreground">{EMPTY}</span>;
  return (
    <Pista contenido={origen.nombre}>
      <Badge variant="outline" size="sm" className="font-medium text-muted-foreground">
        {origen.corta}
      </Badge>
    </Pista>
  );
}

export function TablaPublicaciones({
  filas,
  cargando,
  clave,
  direccion,
  onOrdenar,
  corteNovedades,
  ahora,
}: {
  filas: TimelineItem[];
  cargando: boolean;
  clave: keyof TimelineItem;
  direccion: DireccionOrden;
  onOrdenar: (clave: keyof TimelineItem) => void;
  corteNovedades: string | null;
  ahora: Date;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1040px] table-fixed border-collapse">
        <colgroup>
          {COLUMNAS.map((columna) => (
            <col key={columna.key} className={columna.ancho} />
          ))}
        </colgroup>
        <thead>
          <tr className="border-b border-border/70">
            {COLUMNAS.map((columna) => {
              const activa = clave === columna.key;
              return (
                <th
                  key={columna.key}
                  scope="col"
                  aria-sort={activa ? (direccion === "asc" ? "ascending" : "descending") : "none"}
                  className={cn("pb-2", columna.align === "right" ? "text-right" : "text-left")}
                >
                  <button
                    type="button"
                    onClick={() => onOrdenar(columna.key)}
                    className={cn(
                      CABECERA_COLUMNA,
                      "group inline-flex items-center gap-1 rounded-sm px-1 py-0.5 transition-colors hover:text-foreground",
                      activa && "text-foreground",
                    )}
                  >
                    {columna.label}
                    <IndicadorOrden direccion={activa ? direccion : false} />
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {cargando
            ? Array.from({ length: 6 }, (_, index) => (
                <tr key={index}>
                  <td colSpan={COLUMNAS.length} className="py-1.5">
                    <Skeleton className="h-5 w-full rounded-sm" />
                  </td>
                </tr>
              ))
            : filas.map((item) => (
                <tr key={item.id_externo} className="border-b border-border/25 transition-colors hover:bg-primary/5">
                  <td className="px-1 py-1.5">
                    <Link
                      href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                      className="flex min-w-0 items-center gap-2 text-tf-meta font-medium hover:underline"
                    >
                      <PuntoNueva nueva={esNueva(item.fecha_publicacion, corteNovedades)} />
                      <span className="min-w-0 truncate">{item.titulo}</span>
                    </Link>
                  </td>
                  <td className="truncate px-1 text-tf-micro text-muted-foreground">
                    {item.organo_contratacion ?? EMPTY}
                  </td>
                  <td className="truncate px-1 text-tf-micro text-muted-foreground">{item.ccaa ?? EMPTY}</td>
                  <td className="truncate px-1 text-tf-micro text-muted-foreground">
                    {item.tipo_contrato ?? EMPTY}
                  </td>
                  <td className="px-1">
                    <span className="flex items-center justify-end gap-2">
                      <BarraImporte importe={item.importe} />
                      <span className="tf-tnum whitespace-nowrap text-tf-micro font-semibold">
                        {formatCurrency(item.importe)}
                      </span>
                    </span>
                  </td>
                  <td className="tf-tnum whitespace-nowrap px-1 text-tf-micro text-muted-foreground">
                    {fechaPublicacionCorta(item.fecha_publicacion, ahora)}
                  </td>
                  <td className="px-1">
                    <StatusBadge value={item.estado} kind="estado" className="h-5 px-1.5 text-tf-micro" />
                  </td>
                  <td className="px-1">
                    <CeldaOrigen fuente={item.fuente} />
                  </td>
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * La misma lista en un teléfono: una ficha por publicación, sin las siete
 * columnas que obligaban a desplazar la tabla en horizontal.
 */
export function ListaPublicacionesMovil({
  filas,
  corteNovedades,
  ahora,
}: {
  filas: TimelineItem[];
  corteNovedades: string | null;
  ahora: Date;
}) {
  return (
    <ul className="flex flex-col">
      {filas.map((item) => {
        const origen = fuenteOrigen(item.fuente);
        return (
          <li key={item.id_externo} className="border-b border-border/25 last:border-b-0">
            <Link
              href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
              className="flex min-h-11 flex-col justify-center gap-1 py-2 transition-colors active:bg-primary/10 active:duration-0"
            >
              <span className="flex items-center gap-2">
                <PuntoNueva nueva={esNueva(item.fecha_publicacion, corteNovedades)} />
                <span className="min-w-0 flex-1 truncate text-tf-meta font-medium">{item.titulo}</span>
                <span className="tf-tnum flex-none text-tf-meta font-semibold">
                  {formatCompactCurrency(item.importe)}
                </span>
              </span>
              <span className="flex items-center gap-2 pl-3.5">
                <span className="min-w-0 flex-1 truncate text-tf-micro text-muted-foreground">
                  {[
                    item.organo_contratacion,
                    fechaPublicacionCorta(item.fecha_publicacion, ahora),
                    origen?.corta,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                <StatusBadge value={item.estado} kind="estado" className="h-5 flex-none px-1.5 text-tf-micro" />
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
