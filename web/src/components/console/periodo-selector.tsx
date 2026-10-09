"use client";

/**
 * El selector de periodo de las vistas de métricas (Rendimiento, Dirección).
 *
 * Un `Segmented` (botones con `aria-pressed` dentro de un `role="group"` con
 * nombre) y no un `tablist`: no conmuta entre paneles, acota la ventana de la
 * que hablan todos. La elección vive en `?periodo=` —la escribe el llamante—
 * para que una ventana concreta se pueda compartir y recargar.
 */
import { Segmented } from "./panel";
import { PERIODOS, type PeriodoClave } from "@/lib/periodo";

const OPCIONES = PERIODOS.map((opcion) => ({ value: opcion.clave, label: opcion.label }));

export function PeriodoSelector({
  periodo,
  onChange,
}: {
  periodo: PeriodoClave;
  onChange: (periodo: PeriodoClave) => void;
}) {
  return <Segmented aria-label="Periodo de las métricas" value={periodo} onChange={onChange} options={OPCIONES} />;
}
