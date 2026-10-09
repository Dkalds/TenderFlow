"use client";

/**
 * Apuntar la próxima acción de una oportunidad **desde su fila**.
 *
 * «Sin próxima acción» llevaba encendido desde siempre porque la única forma de
 * apagarlo estaba en el inspector, que solo existe desde `xl` y cuyo formulario
 * caía bajo el pliegue. La oportunidad que no tiene siguiente paso no necesita
 * otro «Abrir ficha»: necesita que apuntarlo cueste un texto y una fecha.
 *
 * Lo que se guarda es una **tarea** (`POST /pursuits/{id}/tasks`): la API deriva
 * de ella la próxima acción de la oportunidad, así que no hay dos conceptos que
 * mantener a mano.
 *
 * Capa flotante y no campos en la fila: en 176 px de columna no caben, y en
 * móvil la fila es una ficha que ya va justa.
 */

import * as React from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface AccionApuntada {
  titulo: string;
  vence: string | null;
}

export function ApuntarAccion({
  guardando,
  onGuardar,
}: {
  guardando: boolean;
  /** `alGuardar` se llama cuando la API confirma: es lo que cierra la capa. */
  onGuardar: (accion: AccionApuntada, alGuardar: () => void) => void;
}) {
  const [abierto, setAbierto] = React.useState(false);
  const [titulo, setTitulo] = React.useState("");
  const [vence, setVence] = React.useState("");
  const texto = titulo.trim();

  const guardar = (event: React.FormEvent) => {
    event.preventDefault();
    if (!texto) return;
    onGuardar({ titulo: texto, vence: vence || null }, () => {
      setAbierto(false);
      setTitulo("");
      setVence("");
    });
  };

  return (
    <Popover open={abierto} onOpenChange={setAbierto}>
      <PopoverTrigger asChild>
        <button
          type="button"
          // La fila selecciona al pulsarla; el botón no tiene por qué.
          onClick={(event) => event.stopPropagation()}
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "truncate border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
          )}
        >
          Apuntar acción
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[300px] max-w-[calc(100vw-2rem)] p-3"
        // La capa se pinta fuera de la fila pero sus eventos burbujean por el
        // árbol de React hasta ella: sin esto, un clic dentro la seleccionaba y
        // un doble clic sobre el texto abría la ficha.
        onClick={(event) => event.stopPropagation()}
        onDoubleClick={(event) => event.stopPropagation()}
      >
        <form onSubmit={guardar} className="space-y-2">
          <h3 className="text-tf-body font-semibold">Próxima acción</h3>
          <Input
            aria-label="Qué hay que hacer"
            value={titulo}
            onChange={(event) => setTitulo(event.target.value)}
            placeholder="p. ej. pedir el pliego técnico"
            maxLength={300}
            className="h-8 text-tf-meta"
          />
          <Input
            type="date"
            aria-label="Para cuándo"
            value={vence}
            onChange={(event) => setVence(event.target.value)}
            className="h-8 text-tf-meta"
          />
          <div className="flex items-center gap-2">
            <p className="flex-1 text-tf-micro text-muted-foreground">
              Se guarda como tarea de la oportunidad.
            </p>
            <Button type="submit" size="sm" disabled={!texto || guardando}>
              {guardando ? "Guardando…" : "Guardar"}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
