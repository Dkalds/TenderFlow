"use client";

/**
 * F1.6 — etiquetas de organización sobre un favorito, una oportunidad o una
 * cuenta: los chips y el selector para ponerlas y quitarlas.
 *
 * El color va en un punto junto al nombre y no en el texto ni en el fondo: el
 * nombre se lee siempre con el contraste del tema, elija el equipo el color
 * que elija.
 */
import * as React from "react";
import { Loader2, Plus, Tag } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  COLORES_ETIQUETA,
  MAX_ETIQUETAS,
  type EtiquetaAplicada,
  type ObjetoEtiquetable,
  useCambiarEtiqueta,
  useCrearEtiqueta,
  useEtiquetas,
} from "@/hooks/use-etiquetas";
import { cn } from "@/lib/utils";

export function EtiquetaChip({ etiqueta }: { etiqueta: Pick<EtiquetaAplicada, "nombre" | "color"> }) {
  return (
    <span className="inline-flex h-5 max-w-[14rem] items-center gap-1 rounded-full border border-border/70 bg-background px-2 text-[10.5px] font-medium">
      {/* `fill` es un atributo de presentación SVG, no un estilo inline: la CSP
          (`style-src`, C2.8) no lo gobierna y el color sigue viniendo del dato. */}
      <svg aria-hidden="true" viewBox="0 0 6 6" className="h-1.5 w-1.5 flex-none">
        <circle cx="3" cy="3" r="3" fill={etiqueta.color} />
      </svg>
      <span className="truncate">{etiqueta.nombre}</span>
    </span>
  );
}

export function EtiquetaChips({
  etiquetas,
  className,
}: {
  etiquetas: readonly EtiquetaAplicada[] | undefined;
  className?: string;
}) {
  if (!etiquetas?.length) return null;
  return (
    <ul aria-label="Etiquetas" className={cn("flex flex-wrap gap-1", className)}>
      {etiquetas.map((etiqueta) => (
        <li key={etiqueta.id}>
          <EtiquetaChip etiqueta={etiqueta} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Selector de etiquetas de **un** objeto. `aplicadas` viene del llamante
 * (normalmente de `useEtiquetasDe` para toda la lista), así que abrirlo no
 * cuesta una petición por fila.
 */
export function EtiquetasEditor({
  objetoTipo,
  objetoId,
  aplicadas,
  descripcion,
}: {
  objetoTipo: ObjetoEtiquetable;
  objetoId: string;
  aplicadas: readonly EtiquetaAplicada[] | undefined;
  /** Qué se etiqueta, para el nombre accesible del botón. */
  descripcion: string;
}) {
  const [abierto, setAbierto] = React.useState(false);
  const [nombre, setNombre] = React.useState("");
  const [color, setColor] = React.useState<string>(COLORES_ETIQUETA[0]);
  const etiquetas = useEtiquetas();
  const cambiar = useCambiarEtiqueta();
  const crear = useCrearEtiqueta();
  const idsAplicadas = new Set((aplicadas ?? []).map((e) => e.id));
  const todas = etiquetas.data ?? [];
  const llena = todas.length >= MAX_ETIQUETAS;
  const baseId = `etiquetas-${objetoTipo}-${objetoId}`;

  const alternar = (etiquetaId: number, aplicar: boolean) =>
    cambiar.mutate(
      { etiquetaId, objetoTipo, objetoId, aplicar },
      {
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "No se pudo cambiar la etiqueta"),
      },
    );

  const crearYAplicar = async (event: React.FormEvent) => {
    event.preventDefault();
    const limpio = nombre.trim();
    if (!limpio) return;
    try {
      const etiqueta = await crear.mutateAsync({ nombre: limpio, color });
      setNombre("");
      alternar(etiqueta.id, true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo crear la etiqueta");
    }
  };

  return (
    <Popover open={abierto} onOpenChange={setAbierto}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 gap-1 px-2 text-xs"
          aria-label={`Etiquetas de ${descripcion}`}
        >
          <Tag className="h-3.5 w-3.5" aria-hidden="true" />
          Etiquetas
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-3">
        <fieldset>
          <legend className="mb-2 text-xs font-semibold">Etiquetas del equipo</legend>
          {etiquetas.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-label="Cargando etiquetas" />
          ) : todas.length === 0 ? (
            <p className="text-[11.5px] text-muted-foreground">
              Tu organización aún no tiene etiquetas. Crea la primera abajo.
            </p>
          ) : (
            <ul className="max-h-56 space-y-1 overflow-y-auto">
              {todas.map((etiqueta) => {
                const id = `${baseId}-${etiqueta.id}`;
                return (
                  <li key={etiqueta.id} className="flex items-center gap-2">
                    <Checkbox
                      id={id}
                      checked={idsAplicadas.has(etiqueta.id)}
                      disabled={cambiar.isPending}
                      onCheckedChange={(value) => alternar(etiqueta.id, value === true)}
                    />
                    <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer">
                      <EtiquetaChip etiqueta={etiqueta} />
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </fieldset>

        <form onSubmit={crearYAplicar} className="mt-3 space-y-2 border-t border-border/60 pt-3">
          <label htmlFor={`${baseId}-nueva`} className="block text-xs font-medium">
            Nueva etiqueta
          </label>
          <div className="flex gap-1.5">
            <Input
              id={`${baseId}-nueva`}
              value={nombre}
              maxLength={40}
              disabled={llena}
              onChange={(event) => setNombre(event.target.value)}
              placeholder="Q4, prioridad…"
              className="h-8 text-xs"
            />
            <Button
              type="submit"
              size="sm"
              className="h-8"
              disabled={llena || !nombre.trim() || crear.isPending}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="sr-only">Crear y aplicar</span>
            </Button>
          </div>
          <div role="radiogroup" aria-label="Color" className="flex gap-1.5">
            {COLORES_ETIQUETA.map((opcion) => (
              <button
                key={opcion}
                type="button"
                role="radio"
                aria-checked={color === opcion}
                aria-label={`Color ${opcion}`}
                onClick={() => setColor(opcion)}
                className={cn(
                  "h-5 w-5 rounded-full border-2",
                  color === opcion ? "border-foreground" : "border-transparent",
                )}
              >
                <svg aria-hidden="true" viewBox="0 0 16 16" className="h-full w-full">
                  <circle cx="8" cy="8" r="8" fill={opcion} />
                </svg>
              </button>
            ))}
          </div>
          {llena ? (
            <p className="text-[11px] text-muted-foreground">
              Tu organización tiene {MAX_ETIQUETAS} etiquetas, el máximo. Borra alguna para crear
              otra.
            </p>
          ) : null}
        </form>
      </PopoverContent>
    </Popover>
  );
}
