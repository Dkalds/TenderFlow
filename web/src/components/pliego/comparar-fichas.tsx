"use client";

import { AlertCircle } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type CeldaComparacion,
  type FilaComparacion,
  useCompararFichas,
} from "@/hooks/use-comparar-fichas";

/**
 * F2.8 — tabla de las familias de la ficha de dos o tres expedientes.
 *
 * Determinista y sin LLM: pinta lo que devuelve `POST /licitaciones/comparar`,
 * sin sintetizar. Una familia vacía **se enseña vacía** —«no lo publica»— y
 * las que no publica ningún pliego se pliegan al final, pero no desaparecen:
 * que los tres callen sobre la solvencia técnica también es información.
 */

function Celda({ celda }: { celda: CeldaComparacion | undefined }) {
  if (!celda || celda.n === 0) {
    return <span className="text-muted-foreground">No lo publica</span>;
  }
  const ejemplos = celda.ejemplos ?? [];
  const resto = celda.n - ejemplos.length;
  return (
    <ul className="space-y-1">
      {ejemplos.map((ejemplo, i) => (
        <li key={i} className="leading-snug">
          {ejemplo}
        </li>
      ))}
      {resto > 0 && <li className="text-muted-foreground">y {resto} más</li>}
    </ul>
  );
}

function Filas({ filas, ids }: { filas: FilaComparacion[]; ids: string[] }) {
  return (
    <>
      {filas.map((fila) => (
        <tr key={fila.familia} className="border-b border-border/50 align-top last:border-b-0">
          <th scope="row" className="w-44 py-2 pr-3 text-left font-medium text-muted-foreground">
            {fila.etiqueta}
          </th>
          {ids.map((id) => (
            <td key={id} className="py-2 pr-3">
              <Celda celda={fila.celdas?.find((c) => c.licitacion_id === id)} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function ComparacionFichasTabla({
  ids,
  etiquetas = {},
}: {
  ids: string[];
  /** Nombre corto por id para la cabecera; sin él se usa el id. */
  etiquetas?: Record<string, string | null | undefined>;
}) {
  const consulta = useCompararFichas(ids);

  if (ids.length < 2) {
    return <p className="text-sm text-muted-foreground">Elige al menos dos expedientes.</p>;
  }
  if (consulta.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (consulta.error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        No se pudieron comparar las fichas. {(consulta.error as Error).message}
      </p>
    );
  }
  const data = consulta.data;
  if (!data) return null;

  const columnas = data.licitacion_ids?.length ? data.licitacion_ids : ids;
  const filas = data.filas ?? [];
  const conDatos = filas.filter((f) => !f.vacia_en_todos);
  const vacias = filas.filter((f) => f.vacia_en_todos);
  const sinFicha = data.sin_ficha ?? [];
  const nombre = (id: string) => etiquetas[id] || id;

  return (
    <div className="space-y-3">
      {sinFicha.length > 0 && (
        <p
          role="status"
          className="flex gap-2 rounded-lg border border-warning/30 bg-warning/10 p-2.5 text-xs text-warning"
        >
          <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Sin ficha del pliego extraída todavía: {sinFicha.map(nombre).join(", ")}. Su columna en
            blanco no significa que el pliego no exija nada.
          </span>
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Comparación de las fichas del pliego, familia a familia</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="py-2 pr-3 text-left font-medium text-muted-foreground">
                Familia
              </th>
              {columnas.map((id) => (
                <th key={id} scope="col" className="py-2 pr-3 text-left font-medium">
                  <span className="line-clamp-2">{nombre(id)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <Filas filas={conDatos} ids={columnas} />
          </tbody>
        </table>
      </div>
      {vacias.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-muted-foreground">
            Ningún pliego publica {vacias.length === 1 ? "esta familia" : `estas ${vacias.length} familias`}
          </summary>
          <ul className="mt-2 list-disc pl-5 text-muted-foreground">
            {vacias.map((f) => (
              <li key={f.familia}>{f.etiqueta}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
