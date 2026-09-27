"use client";

import { useEffect } from "react";
import { PanelError } from "@/components/console/panel";
import { reportError } from "@/lib/report-error";

/**
 * Fallo al pintar una pantalla de la consola. El marco (rail, barra de ámbito)
 * sigue en pie: este límite solo sustituye el contenido.
 *
 * Es un `PanelError` como cualquier otro fallo de la consola (decisión D6):
 * mensaje humano, «Reintentar» y el detalle técnico plegado, con el `digest`
 * —el mismo que viaja en el reporte— para que un «Código: 1a2b3c» en un correo
 * de soporte se cruce con la línea del log. El mensaje crudo del error va
 * también plegado: es para soporte, no para quien estaba trabajando.
 *
 * Antes era una tarjeta con «Error» a secas, un triángulo y «Por favor,
 * inténtalo de nuevo», y el fallo se quedaba en la consola del navegador; ahora
 * se reporta como los de `global-error`.
 */
export default function DashboardError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  /** Vuelve a pedir y a pintar lo que falló (Next 16.3; `reset` solo repinta). */
  retry: () => void;
}) {
  useEffect(() => {
    reportError("DashboardError", error);
  }, [error]);

  const detalle = [error.digest ? `Código: ${error.digest}` : null, error.message || null].filter(Boolean).join(" · ");

  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-12">
      <PanelError
        title="No se ha podido cargar esta pantalla"
        message="Vuelve a intentarlo. Si se repite, avísanos con el código del detalle técnico."
        detail={detalle || undefined}
        onRetry={retry}
      />
    </div>
  );
}
