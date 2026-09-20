"use client";

import Link from "next/link";
import { BriefcaseBusiness, RadioTower } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";

/**
 * El vacío de la pantalla entera: no hay ninguna oportunidad todavía.
 *
 * Distinto del vacío de una columna, que usa `PanelEmpty` y dice que esa fase
 * está libre. Aquí lo que falta es el primer paso del producto, así que lo
 * único que se ofrece es el camino para darlo.
 *
 * Lleva `role="status"`: sustituye a los esqueletos de carga, y pasar de
 * «cargando» a «no hay nada» es un cambio que el lector tiene que oír.
 */
export function TableroVacio() {
  return (
    <div className="grid flex-1 place-items-center p-10">
      <div
        role="status"
        className="border-border/60 max-w-[480px] rounded-xl border border-dashed px-8 py-11 text-center"
      >
        <span className="bg-primary/8 border-primary/15 text-primary mx-auto mb-3.5 grid h-11 w-11 place-items-center rounded-[11px] border">
          <BriefcaseBusiness className="h-5 w-5" aria-hidden="true" />
        </span>
        <h3 className="font-display mb-1.5 text-tf-lede leading-[1.3] font-semibold">
          Todavía no hay oportunidades
        </h3>
        <p className="text-muted-foreground mb-4 text-tf-body leading-[1.6] text-pretty">
          Convierte una señal del Radar en una oportunidad de equipo para empezar a hacerle
          seguimiento.
        </p>
        <Link href="/radar" className={buttonVariants({ size: "sm" })}>
          <RadioTower className="h-3.5 w-3.5" aria-hidden="true" />
          Ir al Radar
        </Link>
      </div>
    </div>
  );
}
