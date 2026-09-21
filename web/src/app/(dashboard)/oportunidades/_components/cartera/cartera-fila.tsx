"use client";

/**
 * Una fila de la tabla de Cartera.
 *
 * Todo lo accionable del contrato vive aquí y a **todos** los anchos: abrir la
 * oportunidad, ver la de renovación o prepararla. Lo que la fila no cabe —el
 * resto del contrato y su cronología— es lo que enseña el inspector, y por eso
 * el botón que lo abre sólo existe a partir de `xl`: por debajo no habría
 * dónde pintarlo, y un control que no hace nada es peor que su ausencia.
 */
import Link from "next/link";
import { TableCell, TableRow } from "@/components/ui/table";
import { fechaCorta } from "@/lib/adjudicacion-prevista";
import type { ContratoCartera } from "@/lib/cartera";
import { plazoRestante, urgenciaCartera } from "@/lib/cartera";
import { cn, EMPTY, formatCompactCurrency } from "@/lib/utils";
import { PrepararRenovacion } from "../preparar-renovacion";
import { OrigenFin } from "./origen-fin";

export function CarteraFila({
  contrato,
  activo,
  onSeleccionar,
}: {
  contrato: ContratoCartera;
  activo: boolean;
  onSeleccionar: () => void;
}) {
  const urgencia = urgenciaCartera(contrato);
  const nombre = contrato.titulo ?? contrato.licitacion_id;

  return (
    <TableRow data-state={activo ? "selected" : undefined}>
      <TableCell className="max-w-[28rem]">
        <Link
          href={`/oportunidades/${contrato.pursuit_id}`}
          className="line-clamp-2 font-medium hover:underline"
        >
          {nombre}
        </Link>
        <p className="truncate text-[10.5px] text-muted-foreground">
          {contrato.organo_contratacion ?? "Órgano sin publicar"}
          {contrato.tecnologia ? ` · ${contrato.tecnologia}` : null}
        </p>
        {contrato.renovacion_pursuit_id ? (
          <Link
            href={`/oportunidades/${contrato.renovacion_pursuit_id}`}
            className="text-[10.5px] font-medium text-primary hover:underline"
          >
            Ver oportunidad de renovación
          </Link>
        ) : (
          <PrepararRenovacion
            carteraId={contrato.id}
            licitacionVigente={contrato.licitacion_id}
            titulo={nombre}
          />
        )}
      </TableCell>
      <TableCell>
        <span className="tf-tnum whitespace-nowrap">
          {contrato.fecha_fin_efectiva ? fechaCorta(contrato.fecha_fin_efectiva) : EMPTY}
        </span>
        <OrigenFin origen={contrato.fecha_fin_origen} />
        <p
          className={cn(
            "text-[10.5px]",
            urgencia === "vencido" || urgencia === "pronto"
              ? "font-medium text-[hsl(var(--warning))]"
              : "text-muted-foreground",
          )}
        >
          {plazoRestante(contrato)}
        </p>
      </TableCell>
      <TableCell className="tf-tnum text-right">{contrato.prorrogas_aplicadas}</TableCell>
      <TableCell>
        {contrato.relicitacion_desde && contrato.relicitacion_hasta ? (
          <>
            <span className="tf-tnum whitespace-nowrap">
              {fechaCorta(contrato.relicitacion_desde)} – {fechaCorta(contrato.relicitacion_hasta)}
            </span>
            <p className="text-[10.5px] text-muted-foreground">
              Estimación: 6 a 3 meses antes del fin
            </p>
          </>
        ) : (
          <span className="text-muted-foreground">Sin fecha de fin</span>
        )}
      </TableCell>
      <TableCell className="tf-tnum text-right">
        {contrato.importe_adjudicado != null
          ? formatCompactCurrency(contrato.importe_adjudicado)
          : EMPTY}
      </TableCell>
      <TableCell className="hidden text-right xl:table-cell">
        {/* Botón propio y no la fila entera como control: la fila ya lleva dos
            enlaces y el diálogo de renovación dentro, y anidarlos en un
            `role="button"` es el `nested-interactive` que el Radar ya se comió
            (C7.1). */}
        <button
          type="button"
          aria-label={`Ver detalle de ${nombre}`}
          aria-current={activo ? "true" : undefined}
          onClick={onSeleccionar}
          className={cn(
            "tf-pressable h-6 rounded-md border px-2 text-[10.5px] font-medium transition-colors duration-110",
            activo
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border/70 text-muted-foreground hover:text-foreground",
          )}
        >
          Detalle
        </button>
      </TableCell>
    </TableRow>
  );
}
