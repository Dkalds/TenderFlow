"use client";

/**
 * F1.1 — los tres filtros del ámbito que sólo aplica el listado: procedimiento,
 * provincia e importe máximo.
 *
 * Viven aparte de `scope-bar.tsx` porque tienen un contrato distinto: son
 * opt-in (`FILTROS_OPT_IN` en `lib/navigation.ts`) y sólo aparecen en las
 * pantallas que los declaran. El procedimiento se ofrece con la etiqueta del
 * catálogo de `GET /meta/filters` (F1.7) y viaja como código CODICE; la
 * provincia no tiene catálogo en la API y se escribe tal como la publica la
 * fuente (también se añade pulsando una provincia en Mercado → Geografía).
 */

import * as React from "react";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { useDebounce } from "@/hooks/use-debounce";
import type { MetaFilters } from "@/lib/api-types";
import type { FiltersState } from "@/lib/filters";
import type { GlobalFilterKey } from "@/lib/navigation";
import { resolverCodigo } from "@/lib/procedimientos";
import { formatNumber } from "@/lib/utils";

interface ChipListado {
  key: string;
  value: string;
  remove: () => void;
}

/** Chips de los filtros del listado que la pantalla aplica. */
export function chipsListado(
  filters: FiltersState,
  meta: MetaFilters | undefined,
  shows: (key: GlobalFilterKey) => boolean,
): ChipListado[] {
  const list: ChipListado[] = [];
  if (shows("procedimiento")) {
    for (const codigo of filters.procedimientos) {
      list.push({
        key: "Procedimiento",
        // La chapa enseña la etiqueta; la URL y la query siguen con el código.
        value: resolverCodigo(meta, "procedimiento", codigo)?.etiqueta ?? codigo,
        remove: () => filters.setProcedimientos(filters.procedimientos.filter((c) => c !== codigo)),
      });
    }
  }
  if (shows("provincia")) {
    for (const provincia of filters.provincias) {
      list.push({
        key: "Provincia",
        value: provincia,
        remove: () => filters.setProvincias(filters.provincias.filter((p) => p !== provincia)),
      });
    }
  }
  if (shows("importe_max") && filters.importeMax != null) {
    list.push({
      key: "Importe",
      value: `< ${formatNumber(filters.importeMax)} €`,
      remove: () => filters.setImporteMax(null),
    });
  }
  return list;
}

const LABEL = "mb-1.5 block font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground";

export function FiltrosListadoEditor({
  filters,
  meta,
  shows,
}: {
  filters: FiltersState;
  meta: MetaFilters | undefined;
  shows: (key: GlobalFilterKey) => boolean;
}) {
  const catalogo = React.useMemo(() => meta?.procedimiento ?? [], [meta]);
  const etiquetaDe = React.useCallback(
    (codigo: string) => catalogo.find((o) => o.codigo === codigo)?.etiqueta ?? codigo,
    [catalogo],
  );
  const [provincia, setProvincia] = React.useState("");

  return (
    <>
      {shows("procedimiento") && (
        <div>
          <span className={LABEL}>Procedimiento</span>
          <MultiSelect
            aria-label="Añadir procedimiento al ámbito"
            options={catalogo.map((o) => o.codigo)}
            selected={filters.procedimientos}
            onChange={filters.setProcedimientos}
            placeholder="Añadir procedimiento…"
            optionLabel={etiquetaDe}
          />
        </div>
      )}

      {shows("provincia") && (
        <div>
          <label htmlFor="scope-provincia" className={LABEL}>
            Provincia
          </label>
          <Input
            id="scope-provincia"
            className="bg-background/70 h-8 w-full rounded-md text-xs"
            placeholder="Escribe una provincia y pulsa Intro"
            value={provincia}
            onChange={(event) => setProvincia(event.target.value)}
            onKeyDown={(event) => {
              const valor = provincia.trim();
              if (event.key !== "Enter" || !valor) return;
              event.preventDefault();
              if (!filters.provincias.includes(valor)) filters.setProvincias([...filters.provincias, valor]);
              setProvincia("");
            }}
          />
        </div>
      )}

      {shows("importe_max") && <ImporteMaximo filters={filters} />}
    </>
  );
}

/** Importe máximo con el mismo debounce que el mínimo: sin él cada tecla es un refetch. */
function ImporteMaximo({ filters }: { filters: FiltersState }) {
  const [valor, setValor] = React.useState<number | "">(filters.importeMax ?? "");
  const debounced = useDebounce(valor, 400);
  const [externoPrevio, setExternoPrevio] = React.useState(filters.importeMax);
  if (filters.importeMax !== externoPrevio) {
    setExternoPrevio(filters.importeMax);
    const actual = valor === "" ? null : Number(valor);
    if (actual !== filters.importeMax) setValor(filters.importeMax ?? "");
  }
  React.useEffect(() => {
    const next = debounced === "" ? null : Number(debounced);
    if (next !== filters.importeMax) filters.setImporteMax(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo reacciona al valor debounced
  }, [debounced]);

  return (
    <div>
      <label htmlFor="scope-importe-max" className={LABEL}>
        Importe máximo
      </label>
      <Input
        id="scope-importe-max"
        type="number"
        min={0}
        className="bg-background/70 h-8 w-full rounded-md text-xs"
        placeholder="Sin máximo"
        value={valor}
        onChange={(event) => setValor(event.target.value ? Number(event.target.value) : "")}
      />
    </div>
  );
}
