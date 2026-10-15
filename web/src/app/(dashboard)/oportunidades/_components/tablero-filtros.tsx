"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FiltroEtiquetaSelect } from "@/components/etiquetas/filtro-etiqueta";
import { useActiveOrganizationId, useOrganizationMembers } from "@/hooks/use-organization";
import { PLAZOS, TODOS_LOS_RESPONSABLES, type FiltrosTablero } from "../_lib/filtros-tablero";
import { ExportarCrm } from "./exportar-crm";

/**
 * Los controles que gobiernan las seis columnas. Viven en la cabecera del
 * espacio, no dentro del tablero: filtran todo a la vez, no una columna.
 *
 * Todos filtran **en servidor** (`_lib/filtros-tablero.ts`): texto, etiqueta,
 * responsable y plazo de presentación. El filtro de etiqueta es el compartido
 * con el Radar y Detalle (`components/etiquetas/filtro-etiqueta.tsx`), que
 * desaparece cuando la organización no tiene ninguna; el de responsable, cuando
 * no hay a quién elegir.
 */
export function TableroFiltros({
  filtros,
  onCambiar,
}: {
  filtros: FiltrosTablero;
  onCambiar: (cambio: Partial<FiltrosTablero>) => void;
}) {
  return (
    <div className="flex flex-none flex-wrap items-center justify-end gap-2">
      {/* F6.3 — el tablero entero como CSV para el CRM. */}
      <ExportarCrm />
      <FiltroResponsable value={filtros.responsable} onChange={(responsable) => onCambiar({ responsable })} />
      <Select
        value={filtros.plazo}
        onValueChange={(plazo) => onCambiar({ plazo: plazo as FiltrosTablero["plazo"] })}
      >
        <SelectTrigger className="h-7 w-40 text-tf-meta" aria-label="Filtrar por plazo de presentación">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PLAZOS.map((plazo) => (
            <SelectItem key={plazo.value} value={plazo.value}>
              {plazo.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <FiltroEtiquetaSelect
        value={filtros.etiqueta}
        onChange={(etiqueta) => onCambiar({ etiqueta })}
        alcance="en el tablero"
      />
      <label className="relative block w-56 flex-none" htmlFor="pursuit-search">
        <Search
          className="text-muted-foreground pointer-events-none absolute top-1.5 left-2.5 h-3.5 w-3.5"
          aria-hidden="true"
        />
        <span className="sr-only">Buscar oportunidad</span>
        <Input
          id="pursuit-search"
          className="h-7 pl-8 text-tf-meta"
          placeholder="Título, referencia o responsable"
          value={filtros.q}
          onChange={(event) => onCambiar({ q: event.target.value })}
        />
      </label>
    </div>
  );
}

/**
 * Los miembros activos de la organización. Con uno solo —la organización
 * personal, o un equipo recién creado— no hay nada que elegir y el control no
 * aparece.
 */
function FiltroResponsable({ value, onChange }: { value: string; onChange: (valor: string) => void }) {
  const miembros = (useOrganizationMembers(useActiveOrganizationId()).data ?? []).filter(
    (miembro) => miembro.status === "active",
  );
  if (miembros.length < 2) return null;
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-7 w-44 text-tf-meta" aria-label="Filtrar por responsable">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={TODOS_LOS_RESPONSABLES}>Todos los responsables</SelectItem>
        {miembros.map((miembro) => (
          <SelectItem key={miembro.user_id} value={String(miembro.user_id)}>
            {miembro.display_name || miembro.email || `Miembro ${miembro.user_id}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
