"use client";

import Link from "next/link";
import {
  CHIP_POR_BANDA,
  claseDeIcono,
  destinoDe,
  etiquetaKind,
  ICONOS,
  plazoChip,
  tipoDeFecha,
  tituloDe,
} from "@/app/(dashboard)/mi-pipeline/_components/agenda/agenda-meta";
import { cn, formatCompactCurrency } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import type { TonoCarril, TramoSemana } from "./tu-dia-semana-data";

/**
 * La clase de fecha en una palabra: el carril es estrecho y «Plazo de
 * presentación» se quedaba en «Plazo de…». La frase entera va para el lector.
 */
const FECHA_CORTA: Record<string, string> = {
  plazo: "Plazo",
  accion: "Acción",
  fin_contrato: "Fin de contrato",
  relicitacion: "Relicitación",
};

function fechaCorta(item: PipelineAgendaItem): string {
  return (item.due_kind && FECHA_CORTA[item.due_kind]) || tipoDeFecha(item);
}

/** Compromisos que se enseñan por carril; el resto, en la agenda. */
const MAX_POR_CARRIL = 3;

const CARRIL_POR_TONO: Record<TonoCarril, { caja: string; titulo: string }> = {
  vencido: { caja: "border-destructive/30 bg-destructive/5", titulo: "text-destructive" },
  hoy: { caja: "border-primary/30 bg-primary/5", titulo: "text-primary" },
  dia: { caja: "border-border/60", titulo: "text-foreground" },
};

/**
 * Un compromiso dentro de su carril. El vocabulario (icono, chip, clase de
 * fecha) es el de la Agenda (`agenda-meta.ts`): la misma fila se lee igual
 * entres por donde entres.
 */
function TarjetaCompromiso({ item }: { item: PipelineAgendaItem }) {
  const Icono = ICONOS[claseDeIcono(item)];
  return (
    <Link
      href={destinoDe(item)}
      className="flex min-w-0 flex-col gap-1 rounded-md border border-border/60 bg-card px-2 py-1.5 transition-colors hover:border-primary/50 active:bg-primary/10 active:duration-0"
    >
      <span className="flex items-center gap-1.5">
        <Icono className="h-3 w-3 flex-none text-muted-foreground" aria-hidden="true" />
        <span className="sr-only">
          {etiquetaKind(item)} · {tipoDeFecha(item)}:
        </span>
        <span aria-hidden="true" className="min-w-0 flex-1 truncate text-tf-micro text-muted-foreground">
          {fechaCorta(item)}
        </span>
        <span
          className={cn(
            "tf-tnum flex-none rounded-md px-1.5 text-tf-micro font-semibold",
            CHIP_POR_BANDA[item.urgencia],
          )}
        >
          {plazoChip(item)}
        </span>
      </span>
      <span className="line-clamp-2 text-tf-meta font-medium leading-snug">{tituloDe(item)}</span>
      {item.organo && <span className="truncate text-tf-micro text-muted-foreground">{item.organo}</span>}
      {item.importe_eur != null && (
        <span className="tf-tnum text-tf-meta font-semibold">{formatCompactCurrency(item.importe_eur)}</span>
      )}
    </Link>
  );
}

/**
 * La semana de «Tu día»: un carril por día con algo que hacer, lo vencido
 * delante y los días sin nada juntos en un hueco estrecho. En escritorio va en
 * fila, como un calendario; en un teléfono, en columna, día bajo día.
 */
export function SemanaEnCarriles({ tramos }: { tramos: TramoSemana[] }) {
  return (
    <div className="relative md:overflow-x-auto">
      <ol className="flex flex-col gap-2 md:min-w-[720px] md:flex-row md:items-stretch">
        {tramos.map((tramo) => {
          if (tramo.tipo === "libre") {
            return (
              <li
                key={tramo.clave}
                className="flex items-center gap-2 rounded-lg bg-muted/40 px-2.5 py-1.5 text-tf-micro text-muted-foreground md:w-[84px] md:flex-none md:flex-col md:justify-center md:text-center"
              >
                <span className="tf-tnum font-medium">{tramo.etiqueta}</span>
                <span>sin compromisos</span>
              </li>
            );
          }
          const estilo = CARRIL_POR_TONO[tramo.tono];
          const ocultos = tramo.items.length - MAX_POR_CARRIL;
          return (
            <li
              key={tramo.clave}
              className={cn("flex min-w-0 flex-col gap-1.5 rounded-lg border p-2 md:flex-1 md:basis-0", estilo.caja)}
            >
              <h3 className={cn("tf-tnum px-0.5 text-tf-meta font-semibold", estilo.titulo)}>{tramo.etiqueta}</h3>
              {tramo.items.slice(0, MAX_POR_CARRIL).map((item) => (
                <TarjetaCompromiso key={`${item.kind}-${item.licitacion_id}-${item.tarea_id ?? ""}`} item={item} />
              ))}
              {ocultos > 0 && (
                <Link
                  href="/mi-pipeline?vista=agenda"
                  className="px-0.5 text-tf-micro font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  {ocultos} más en la agenda
                </Link>
              )}
              {tramo.items.length === 0 && (
                <p className="px-0.5 text-tf-micro text-muted-foreground">Nada vence hoy</p>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
