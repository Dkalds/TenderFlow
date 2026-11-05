"use client";

import { X } from "lucide-react";
import { chipsListado } from "@/components/layout/scope-filtros-listado";
import type { MetaFilters } from "@/hooks/use-meta-filters";
import { estadoLabel } from "@/lib/estados";
import type { FiltersState } from "@/lib/filters";
import type { GlobalFilterKey } from "@/lib/navigation";
import { formatNumber } from "@/lib/utils";

/** Un filtro activo del ámbito, como chip de la barra: clave, valor y cómo quitarlo. */
export interface Chip {
  key: string;
  value: string;
  remove: () => void;
}

export function ScopeChip({ chip }: { chip: Chip }) {
  return (
    // La clave y la «×» iban con `opacity-60`/`opacity-50` sobre el tinte del
    // chip: 2,4:1, y la «×» medía 8×13 px. Ahora son tinta plena y la «×»
    // ocupa 24×24 (WCAG 2.5.8), con el margen negativo para que el chip no
    // crezca. La clave va en frase y en sans, a 11 px, y el valor a 12 px en
    // medio: la jerarquía la da el peso, no una versal en mono.
    <span className="border-primary-line bg-primary-selected text-primary inline-flex h-6.5 items-center gap-1.5 rounded-md border pr-0.5 pl-2">
      <span className="text-tf-micro leading-none">{chip.key}</span>
      <span className="text-tf-meta max-w-40 truncate leading-none font-medium">{chip.value}</span>
      <button
        type="button"
        aria-label={`Quitar ${chip.key.toLowerCase()} ${chip.value}`}
        onClick={chip.remove}
        className="hover:bg-primary-selected -ml-1 grid h-6 w-6 cursor-pointer place-items-center rounded-sm border-0 bg-transparent p-0 transition-colors"
      >
        <X className="h-3 w-3" aria-hidden="true" />
      </button>
    </span>
  );
}

/** Los chips del ámbito que esta pantalla aplica (`shows`), en el orden de la barra. */
export function chipsDelAmbito(
  filters: FiltersState,
  shows: (key: GlobalFilterKey) => boolean,
  meta: MetaFilters | undefined,
): Chip[] {
  const list: Chip[] = [];
  if (shows("q") && filters.q) {
    list.push({ key: "Busca", value: filters.q, remove: () => filters.setQ("") });
  }
  if (shows("fecha") && (filters.rango.desde || filters.rango.hasta)) {
    const desde = filters.rango.desde ?? "…";
    const hasta = filters.rango.hasta ?? "hoy";
    list.push({
      key: "Periodo",
      value: `${desde} → ${hasta}`,
      remove: () => filters.setRango({ desde: null, hasta: null }),
    });
  }
  if (shows("estado")) {
    // Va antes que los estados sueltos porque es el filtro más amplio de los
    // dos: "abiertas" es una propiedad del expediente, no un código concreto.
    if (filters.soloAbiertas) {
      list.push({
        key: "Estado",
        value: "Sólo abiertas",
        remove: () => filters.setSoloAbiertas(false),
      });
    }
    for (const value of filters.estados) {
      list.push({
        key: "Estado",
        // La chapa muestra la etiqueta pero filtra por el código: el valor
        // que viaja en la URL y en la query sigue siendo `value`.
        value: estadoLabel(value),
        remove: () => filters.setEstados(filters.estados.filter((item) => item !== value)),
      });
    }
  }
  if (shows("ccaa")) {
    for (const value of filters.ccaas) {
      list.push({
        key: "CCAA",
        value,
        remove: () => filters.setCcaas(filters.ccaas.filter((item) => item !== value)),
      });
    }
  }
  if (shows("tecnologia")) {
    for (const value of filters.tecnologias) {
      list.push({
        key: "Tecnología",
        value,
        remove: () => filters.setTecnologias(filters.tecnologias.filter((item) => item !== value)),
      });
    }
  }
  if (shows("importe") && filters.importeMin != null) {
    list.push({
      key: "Importe",
      value: `> ${formatNumber(filters.importeMin)} €`,
      remove: () => filters.setImporteMin(null),
    });
  }
  list.push(...chipsListado(filters, meta, shows));
  return list;
}
