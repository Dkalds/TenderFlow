"use client";

import { Columns3, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { ComparacionFichasTabla } from "@/components/pliego/comparar-fichas";
import { PreguntaComparacion } from "@/components/pliego/pregunta-comparacion";
import { useBandejaComparacion } from "@/hooks/use-comparacion";
import { MAX_COMPARAR } from "@/hooks/use-comparar-fichas";
import { truncate } from "@/lib/utils";

/**
 * F2.8 — marcar expedientes para comparar desde donde se estén mirando.
 *
 * El comparador de Detalle exige tener las filas en la misma tabla; con la
 * bandeja se elige uno en el Radar, otro en la watchlist y un tercero en su
 * ficha, y se comparan las fichas del pliego al final.
 */
export function CompararBoton({
  id,
  titulo,
  className,
}: {
  id: string;
  titulo: string | null | undefined;
  className?: string;
}) {
  const marcado = useBandejaComparacion((s) => s.items.some((i) => i.id === id));
  const alternar = useBandejaComparacion((s) => s.alternar);
  return (
    <button
      type="button"
      aria-pressed={marcado}
      onClick={(event) => {
        event.stopPropagation();
        if (!alternar({ id, titulo: titulo ?? null })) {
          toast.error(
            `Ya hay ${MAX_COMPARAR} expedientes para comparar. Quita uno para añadir otro.`,
          );
        }
      }}
      className={className}
    >
      <Columns3 className="h-3 w-3 shrink-0" aria-hidden="true" />
      {marcado ? "En comparación" : "Comparar"}
    </button>
  );
}

export function BandejaComparacion() {
  const { items, abierta, quitar, vaciar, setAbierta } = useBandejaComparacion();
  if (items.length === 0) return null;

  const ids = items.map((i) => i.id);
  const etiquetas = Object.fromEntries(items.map((i) => [i.id, i.titulo ? truncate(i.titulo, 60) : i.id]));

  return (
    <>
      <div
        role="region"
        aria-label="Expedientes para comparar"
        className="fixed bottom-4 left-1/2 z-40 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center gap-2 rounded-xl border border-border bg-card/95 px-3 py-2 shadow-lg backdrop-blur"
      >
        <span className="text-xs font-medium text-muted-foreground">
          Comparar {items.length}/{MAX_COMPARAR}
        </span>
        <ul className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <li
              key={item.id}
              className="inline-flex max-w-52 items-center gap-1 rounded-md border border-border/70 bg-background px-2 py-0.5 text-xs"
            >
              <span className="truncate">
                {item.titulo ? truncate(item.titulo, 40) : item.id}
              </span>
              <button
                type="button"
                onClick={() => quitar(item.id)}
                aria-label={`Quitar ${item.titulo ?? item.id} de la comparación`}
                className="grid h-5 w-5 place-items-center rounded text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
        <Button size="sm" disabled={items.length < 2} onClick={() => setAbierta(true)}>
          Comparar fichas
        </Button>
        <Button size="sm" variant="ghost" onClick={vaciar}>
          Vaciar
        </Button>
      </div>

      <Dialog open={abierta} onOpenChange={setAbierta}>
        <DialogContent className="mx-4 max-h-[90vh] w-full max-w-6xl overflow-auto">
          <DialogTitle>Comparar fichas del pliego</DialogTitle>
          <DialogDescription>
            Lo que cada pliego dice de cada familia, tal como se extrajo. Sin síntesis: la comparación
            la haces tú. Debajo puedes preguntar sobre los expedientes a la vez.
          </DialogDescription>
          {abierta && <ComparacionFichasTabla ids={ids} etiquetas={etiquetas} />}
          {abierta && <PreguntaComparacion ids={ids} etiquetas={etiquetas} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
