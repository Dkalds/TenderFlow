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

import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

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
    <section className="min-w-0 p-5" aria-label={titulo}>
      <h3 className="font-semibold">{titulo}</h3>
      <p className="text-muted-foreground mt-0.5 text-xs">{descripcion}</p>
      {celdas.length ? (
        <table className="mt-4 w-full text-left text-[12.5px]">
          <caption className="sr-only">{titulo}</caption>
          <thead className="text-muted-foreground text-[10.5px] uppercase">
            <tr className="border-b">
              <th scope="col" className="py-1.5 pr-3 font-medium">
                Corte
              </th>
              <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                n
              </th>
              <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                Baja media
              </th>
              <th scope="col" className="py-1.5 text-right font-medium">
                Adjudicado
              </th>
            </tr>
          </thead>
          <tbody>
            {celdas.map((celda) => {
              const insuficiente = celda.n < minimo;
              return (
                <tr key={celda.clave} className="border-b last:border-b-0">
                  <td className="py-2 pr-3 font-medium">{celda.clave}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatNumber(celda.n)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {insuficiente ? (
                      <span className="text-muted-foreground text-[11px]">menos de {minimo}</span>
                    ) : celda.baja_media == null ? (
                      EMPTY
                    ) : (
                      formatPercent(celda.baja_media * 100)
                    )}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {celda.importe_total == null ? EMPTY : formatCurrency(celda.importe_total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="text-muted-foreground py-8 text-center text-sm">Sin datos para este corte</p>
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
    <div className="grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
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
