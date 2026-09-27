"use client";

import Link from "next/link";
import { RadioTower } from "lucide-react";
import { PanelEmpty } from "@/components/console/panel";
import { buttonVariants } from "@/components/ui/button";

/**
 * El vacío de la pantalla entera: no hay ninguna oportunidad todavía.
 *
 * Distinto del vacío de una columna, que dice que esa fase está libre. Aquí lo
 * que falta es el primer paso del producto, así que lo único que se ofrece es
 * el camino para darlo (el botón primario: es ese primer paso).
 *
 * `PanelEmpty` ya lleva `role="status"`: sustituye a los esqueletos de carga,
 * y pasar de «cargando» a «no hay nada» es un cambio que el lector tiene que
 * oír.
 */
export function TableroVacio() {
  return (
    <div className="grid flex-1 place-items-center p-10">
      <PanelEmpty
        title="Todavía no hay oportunidades"
        hint="Convierte una señal del Radar en una oportunidad de equipo para empezar a hacerle seguimiento."
        action={
          <Link href="/radar" className={buttonVariants({ size: "sm" })}>
            <RadioTower aria-hidden="true" />
            Ir al Radar
          </Link>
        }
      />
    </div>
  );
}
