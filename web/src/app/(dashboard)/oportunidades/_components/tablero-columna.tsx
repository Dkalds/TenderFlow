"use client";

import * as React from "react";
import { PanelEmpty } from "@/components/console/panel";
import { PursuitCard } from "@/components/pursuits/pursuit-card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { esTerminal, type Pursuit } from "@/hooks/use-pursuits";
import type { EtiquetaAplicada } from "@/hooks/use-etiquetas";
import { agruparPorExpediente, type Fase, type FaseKey } from "../_lib/fases";
import { MoverMenu } from "./mover-menu";

/**
 * Una columna del tablero: su cabecera y su zona de soltado.
 *
 * La cabecera dice **cuántas** hay, y nada más. No suma los importes de la
 * columna a propósito: el listado viene paginado, así que esa suma sería la de
 * la página visible presentada como la de la fase, y sumar en cliente un total
 * que el endpoint no dio es justo lo que prohíbe `frontend-data-invariants.md`.
 * Cuando `/pursuits/metrics` devuelva un agregado por fase, la cifra entra
 * aquí; hasta entonces el valor del pipeline vive en la tira de arriba, que sí
 * lo recibe calculado.
 *
 * `aceptaSoltar` lo decide el flujo (`_lib/flujo.ts`) para la tarjeta que se
 * arrastra. Una columna que no la acepta no llama a `preventDefault`, y el
 * navegador enseña el cursor de «aquí no» en vez de dejar soltar para que
 * luego el backend lo rechace. Una tarjeta cerrada no se arrastra ni lleva
 * menú: ya no tiene adónde ir.
 */
export function TableroColumna({
  fase,
  items,
  etiquetasPorId,
  cargando,
  activa,
  aceptaSoltar,
  arrastrandoId,
  onSobrevolar,
  onSalir,
  onSoltarEnColumna,
  onArrastrar,
  onFinArrastre,
  onMover,
}: {
  fase: Fase;
  items: Pursuit[];
  etiquetasPorId: Record<string, readonly EtiquetaAplicada[]>;
  cargando: boolean;
  activa: boolean;
  aceptaSoltar: boolean;
  arrastrandoId: number | null;
  onSobrevolar: () => void;
  onSalir: () => void;
  onSoltarEnColumna: () => void;
  onArrastrar: (pursuit: Pursuit) => void;
  onFinArrastre: () => void;
  onMover: (pursuit: Pursuit, destino: FaseKey) => void;
}) {
  const tarjeta = (pursuit: Pursuit, enExpediente: boolean) => {
    const cerrada = esTerminal(pursuit.status);
    return (
      <PursuitCard
        key={pursuit.id}
        pursuit={pursuit}
        enExpediente={enExpediente}
        etiquetas={etiquetasPorId[String(pursuit.id)]}
        arrastrando={arrastrandoId === pursuit.id}
        onArrastrar={cerrada ? undefined : onArrastrar}
        onSoltar={onFinArrastre}
        acciones={
          cerrada ? undefined : (
            <MoverMenu pursuit={pursuit} onMover={(destino) => onMover(pursuit, destino)} />
          )
        }
      />
    );
  };

  const arrastrandoAjena = arrastrandoId != null && !aceptaSoltar;

  return (
    <section
      aria-label={fase.titulo}
      className={cn(
        "flex min-h-0 min-w-0 flex-col transition-[background-color,opacity] duration-150 ease-out",
        activa ? "bg-primary/[0.06]" : "bg-background",
        arrastrandoAjena && "opacity-55",
      )}
    >
      <div className="flex-none px-3 pt-2.5">
        <div className="flex items-center gap-1.5">
          <h2 className="text-tf-meta font-semibold">{fase.titulo}</h2>
          <div className="flex-1" />
          <span
            className={cn(
              "tf-tnum rounded px-1.5 py-0.5 font-mono text-tf-micro font-medium",
              items.length
                ? "bg-primary/16 text-primary"
                : "bg-muted-foreground/12 text-muted-foreground",
            )}
          >
            {items.length}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 min-h-[28px] text-tf-micro leading-[1.35]">
          {fase.descripcion}
        </p>
      </div>

      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- zona de soltado: arrastrar es un atajo de puntero sobre una acción que el teclado ya tiene entera en el menú «Mover a» de cada tarjeta, así que la zona no necesita rol ni foco propios */}
      <div
        onDragOver={(event) => {
          // Sin `preventDefault` el navegador no considera la zona soltable y
          // el `drop` no llega nunca: es justo lo que se quiere donde el flujo
          // no deja llevar la tarjeta.
          if (!aceptaSoltar) return;
          event.preventDefault();
          onSobrevolar();
        }}
        onDragLeave={onSalir}
        onDrop={(event) => {
          event.preventDefault();
          if (aceptaSoltar) onSoltarEnColumna();
        }}
        className={cn(
          "flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto border-t px-2.5 py-2.5",
          activa ? "border-primary/45" : "border-border/40",
        )}
      >
        {cargando ? (
          <>
            <Skeleton className="h-32 rounded-xl" />
            <Skeleton className="h-32 rounded-xl" />
          </>
        ) : items.length ? (
          agruparPorExpediente(items).map((grupo) =>
            grupo.items.length === 1 ? (
              tarjeta(grupo.items[0], false)
            ) : (
              <section
                key={grupo.licitacionId}
                aria-label={grupo.titulo}
                className="border-border/50 bg-muted/20 rounded-xl border p-1.5"
              >
                <div className="px-1.5 pt-1 pb-1.5">
                  <p className="truncate text-tf-micro leading-snug font-semibold">{grupo.titulo}</p>
                  <p className="text-muted-foreground mt-0.5 text-tf-micro">
                    {grupo.items.length} oportunidades de este expediente
                  </p>
                </div>
                <div className="flex flex-col gap-2">
                  {grupo.items.map((pursuit) => tarjeta(pursuit, true))}
                </div>
              </section>
            ),
          )
        ) : (
          <PanelEmpty message={fase.vacio} />
        )}
      </div>
    </section>
  );
}
