"use client";

/**
 * La cola de trabajo a demanda: lo que pide un usuario y ejecuta el worker
 * (la ficha de un pliego, los embeddings de un expediente, un PDF grande).
 *
 * «En cola» y «En curso» son el estado de ahora, tenga la antigüedad que
 * tenga: un trabajo atascado desde hace un mes es justo lo que hay que ver.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn, formatDateTime, formatNumber } from "@/lib/utils";
import type { EjecucionesResumen, TrabajoResumen } from "../../_hooks/use-ejecuciones";

/** Nombre legible de cada tipo; uno nuevo se enseña con su identificador. */
const TIPO: Record<string, string> = {
  ficha_pliego: "Ficha del pliego",
  embeddings_expediente: "Embeddings del expediente",
  export_pdf: "Exportación a PDF",
};

const CELDA = "px-3 py-2.5 align-top";
const CIFRA = cn(CELDA, "tf-tnum text-right");

function FilaTrabajo({ trabajo }: { trabajo: TrabajoResumen }) {
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className={CELDA}>
        <span className="font-medium">{TIPO[trabajo.tipo] ?? trabajo.tipo}</span>
        {trabajo.ultimo_error && (
          <Pista contenido={trabajo.ultimo_error}>
            <p className="mt-0.5 line-clamp-2 max-w-prose text-tf-meta text-muted-foreground">
              {trabajo.ultimo_error}
            </p>
          </Pista>
        )}
      </td>
      <td className={CIFRA}>{formatNumber(trabajo.pendientes)}</td>
      <td className={CIFRA}>{formatNumber(trabajo.en_curso)}</td>
      <td className={CIFRA}>{formatNumber(trabajo.hechos)}</td>
      <td className={cn(CIFRA, "font-medium", trabajo.fallidos > 0 && "text-destructive")}>
        {formatNumber(trabajo.fallidos)}
      </td>
      <td className={cn(CELDA, "tf-tnum whitespace-nowrap text-tf-meta text-muted-foreground")}>
        {trabajo.ultimo_fallo ? formatDateTime(trabajo.ultimo_fallo) : "—"}
      </td>
    </tr>
  );
}

export function TrabajosCard({ resumen }: { resumen: EjecucionesResumen }) {
  const trabajos = resumen.trabajos ?? [];

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Trabajos a demanda"
        hint={`Lo que piden los usuarios y ejecuta el worker. Hechos y fallidos, de los últimos ${resumen.ventana_dias} días.`}
      />
      {trabajos.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Sin trabajos en la cola"
          hint={`Nadie ha pedido una ficha de pliego ni una exportación grande en ${resumen.horizonte_dias} días.`}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-tf-body">
            <caption className="sr-only">Cola de trabajo a demanda por tipo</caption>
            <thead className="border-y border-border/70">
              <tr>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Trabajo
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2 text-right")}>
                  En cola
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2 text-right")}>
                  En curso
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2 text-right")}>
                  Hechos
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2 text-right")}>
                  Fallidos
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Último fallo
                </th>
              </tr>
            </thead>
            <tbody>
              {trabajos.map((trabajo) => (
                <FilaTrabajo key={trabajo.tipo} trabajo={trabajo} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
