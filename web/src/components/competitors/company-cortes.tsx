"use client";

/**
 * F3.5 — cómo compite este rival según el procedimiento y el tamaño.
 *
 * Dos cortes que el backend calcula sobre la misma actividad filtrada que los
 * totales (`por_procedimiento`, `por_tramo_importe` del perfil). Cada celda
 * trae su `n`; por debajo de `corte_min_n` la baja y el importe llegan nulos y
 * la celda lo dice en vez de enseñar una media de dos contratos. La baja viaja
 * en tanto por uno.
 */

import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn, EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { CompanyCorte } from "./company-profile-types";

function TablaCorte({
  titulo,
  descripcion,
  celdas,
  minimo,
}: {
  titulo: string;
  descripcion: string;
  celdas: CompanyCorte[];
  minimo: number;
}) {
  return (
    <section className="min-w-0 p-4" aria-label={titulo}>
      <h3 className="text-tf-body font-semibold">{titulo}</h3>
      <p className="mt-0.5 text-tf-meta text-muted-foreground">{descripcion}</p>
      {celdas.length ? (
        <table className="mt-4 w-full text-left text-tf-body">
          <caption className="sr-only">{titulo}</caption>
          <thead>
            <tr className="border-b border-border/60">
              <th scope="col" className={cn(CABECERA_COLUMNA, "py-1.5 pr-3")}>
                Corte
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "py-1.5 pr-3 text-right")}>
                Adjudicaciones
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "py-1.5 pr-3 text-right")}>
                Baja media
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "py-1.5 text-right")}>
                Adjudicado
              </th>
            </tr>
          </thead>
          <tbody>
            {celdas.map((celda) => {
              const insuficiente = celda.n < minimo;
              return (
                <tr key={celda.clave} className="border-b border-border/30 last:border-b-0">
                  <td className="py-2 pr-3 font-medium">{celda.clave}</td>
                  <td className="py-2 pr-3 text-right">{formatNumber(celda.n)}</td>
                  <td className="py-2 pr-3 text-right">
                    {insuficiente ? (
                      <span className="text-tf-meta text-muted-foreground">menos de {minimo}</span>
                    ) : celda.baja_media == null ? (
                      EMPTY
                    ) : (
                      formatPercent(celda.baja_media * 100)
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {celda.importe_total == null ? EMPTY : formatCurrency(celda.importe_total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="py-8 text-center text-tf-meta text-muted-foreground">Sin datos para este corte</p>
      )}
    </section>
  );
}

export function CompanyCortes({
  porProcedimiento,
  porTramo,
  minimo,
}: {
  porProcedimiento: CompanyCorte[];
  porTramo: CompanyCorte[];
  minimo: number;
}) {
  return (
    <div className="grid divide-y divide-border/60 lg:grid-cols-2 lg:divide-x lg:divide-y-0">
      <TablaCorte
        titulo="Por procedimiento"
        descripcion="Adjudicaciones y baja media según el tipo de procedimiento"
        celdas={porProcedimiento}
        minimo={minimo}
      />
      <TablaCorte
        titulo="Por tamaño"
        descripcion="Tramos de importe de licitación según los umbrales de la LCSP"
        celdas={porTramo}
        minimo={minimo}
      />
    </div>
  );
}
