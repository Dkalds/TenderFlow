"use client";

/**
 * La lista que acompaña a la red: los mismos pares, como filas de verdad.
 *
 * Es la versión de la red que se recorre con el teclado y que oye el lector de
 * pantalla. Sin empresa elegida lista los pares del más repetido al menos; con
 * una, sólo a sus socios. Cada fila es un botón que elige una empresa —la
 * primera del par, o el socio—, y «Ver todas» vuelve a la lista entera: lo que
 * en el dibujo se hace pulsando otra vez el nodo.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCompactCurrency, formatNumber, truncate } from "@/lib/utils";

import type { FilaAlianza } from "../_hooks/utes-series";
import { BarraPct } from "./dibujos";

/** Caracteres del nombre que caben en el título junto a «Ver todas». */
const LARGO_EN_TITULO = 24;

function Titulo({ elegida }: { elegida: string | null }) {
  if (elegida == null) return <>Las alianzas más repetidas</>;
  if (elegida.length <= LARGO_EN_TITULO) return <>Con quién se alía {elegida}</>;
  // El nombre entero para el lector de pantalla; recortado a la vista.
  return (
    <>
      Con quién se alía <span className="sr-only">{elegida}</span>
      <span aria-hidden="true">{truncate(elegida, LARGO_EN_TITULO)}</span>
    </>
  );
}

export function UtesAlianzas({
  filas,
  elegida,
  isLoading,
  onElegir,
}: {
  filas: FilaAlianza[];
  elegida: string | null;
  isLoading: boolean;
  onElegir: (empresa: string | null) => void;
}) {
  return (
    <Panel className="min-w-0">
      <PanelTitle
        title={<Titulo elegida={elegida} />}
        actions={
          elegida != null && (
            <Button type="button" variant="ghost" size="sm" onClick={() => onElegir(null)}>
              Ver todas
            </Button>
          )
        }
      />
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ninguna alianza que listar"
          hint="Amplía las fechas o quita filtros para ver quién se alía con quién."
        />
      ) : (
        // El relleno deja sitio al contorno de foco, que la caja con scroll recortaría.
        <ul className="relative -mx-1 max-h-72 space-y-0.5 overflow-y-auto p-1">
          {filas.map((fila) => (
            <li key={fila.clave}>
              <button
                type="button"
                onClick={() => onElegir(fila.empresa)}
                className="flex w-full flex-col gap-1 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-primary/5"
              >
                <span className="sr-only">Ver las alianzas de {fila.empresa}: </span>
                <span className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate text-tf-meta font-medium">{fila.nombre}</span>
                  <span className="tf-tnum flex-none text-tf-meta text-muted-foreground">
                    {formatNumber(fila.contratos)} UTE · {formatCompactCurrency(fila.importe)}
                  </span>
                </span>
                <BarraPct pct={fila.pct} className="h-1.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
