"use client";

/**
 * Poner —o corregir— la fecha de fin de un contrato de la cartera.
 *
 * Un contrato cuya fuente no publicó ni fecha de fin ni duración entra en la
 * cartera sin ventana de relicitación, y así se quedaba: la fila decía «sin
 * fecha de fin publicada» y su única acción era «Ver contrato». Lo que le falta
 * es la fecha, y quien ejecuta el contrato la sabe.
 *
 * Se guarda con origen `manual` (`PATCH /pursuits/cartera/{id}`): la
 * resincronización diaria no la pisa, y la pantalla la enseña como lo que es.
 * Por eso sirve también para corregir una fecha **estimada** por duración.
 */

import * as React from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function FechaFinContrato({
  etiqueta,
  inicial,
  guardando,
  onGuardar,
  className,
}: {
  etiqueta: string;
  /** La fecha que el contrato ya tiene, si se está corrigiendo. */
  inicial?: string | null;
  guardando: boolean;
  /** `alGuardar` se llama cuando la API confirma: es lo que cierra la capa. */
  onGuardar: (fecha: string, alGuardar: () => void) => void;
  className?: string;
}) {
  const previa = inicial ? inicial.slice(0, 10) : "";
  const [abierto, setAbierto] = React.useState(false);
  const [fecha, setFecha] = React.useState(previa);

  const guardar = (event: React.FormEvent) => {
    event.preventDefault();
    if (!fecha || fecha === previa) return;
    onGuardar(fecha, () => setAbierto(false));
  };

  return (
    <Popover
      open={abierto}
      onOpenChange={(siguiente) => {
        // Cada apertura parte de lo que hay guardado, no de lo que se dejó a
        // medio escribir la vez anterior.
        if (siguiente) setFecha(previa);
        setAbierto(siguiente);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(event) => event.stopPropagation()}
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "truncate", className)}
        >
          {etiqueta}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[300px] max-w-[calc(100vw-2rem)] p-3"
        onClick={(event) => event.stopPropagation()}
        onDoubleClick={(event) => event.stopPropagation()}
      >
        <form onSubmit={guardar} className="space-y-2">
          <h3 className="text-tf-body font-semibold">Fin del contrato</h3>
          <Input
            type="date"
            aria-label="Fecha de fin del contrato"
            value={fecha}
            onChange={(event) => setFecha(event.target.value)}
            className="h-8 text-tf-meta"
          />
          <div className="flex items-center gap-2">
            <p className="flex-1 text-tf-micro text-muted-foreground">
              De ella sale la ventana de relicitación. Queda como fecha puesta a mano.
            </p>
            <Button type="submit" size="sm" disabled={!fecha || fecha === previa || guardando}>
              {guardando ? "Guardando…" : "Guardar"}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
