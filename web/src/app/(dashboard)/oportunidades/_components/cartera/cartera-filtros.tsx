"use client";

/**
 * Los dos filtros de la Cartera: tecnología y órgano.
 *
 * Recortan la **tabla**, no la franja de KPIs: el endpoint devuelve la cartera
 * entera (decenas de filas, sin paginar), así que filtrar aquí no esconde nada
 * que el usuario no pueda volver a ver. Los totales de arriba siguen hablando
 * de la cartera completa y lo dicen (ADR-014).
 */
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Valor centinela del «sin filtro»: `Select` de Radix no admite `value=""`. */
export const TODOS = "todos";

export function CarteraFiltros({
  opciones,
  tecnologia,
  organo,
  onTecnologia,
  onOrgano,
}: {
  opciones: { tecnologias: string[]; organos: string[] };
  tecnologia: string;
  organo: string;
  onTecnologia: (valor: string) => void;
  onOrgano: (valor: string) => void;
}) {
  return (
    <>
      <Select value={tecnologia} onValueChange={onTecnologia}>
        <SelectTrigger className="h-7 w-40 text-xs" aria-label="Filtrar por tecnología">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={TODOS}>Todas las tecnologías</SelectItem>
          {opciones.tecnologias.map((t) => (
            <SelectItem key={t} value={t}>
              {t}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={organo} onValueChange={onOrgano}>
        <SelectTrigger className="h-7 w-48 text-xs" aria-label="Filtrar por órgano">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={TODOS}>Todos los órganos</SelectItem>
          {opciones.organos.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </>
  );
}
