"use client";

/**
 * Buscador de órganos reales para una cuenta, con selección múltiple.
 *
 * Sustituye al campo de texto libre de la primera versión de /cuentas, que
 * guardaba lo que se tecleara: «Ayuntamiento de Madrid» no es el nombre de
 * ningún órgano del corpus —Madrid contrata a través de seis—, y una cuenta
 * con ese nombre no casaba con ninguna licitación ni avisaba de nada, sin que
 * nada lo dijera. Aquí sólo se puede elegir un órgano que existe, con sus
 * expedientes a la vista, y varios a la vez: un cliente son todos sus órganos.
 *
 * Un órgano que ya es de otra cuenta sale deshabilitado y dice de cuál: un
 * órgano es de una sola cuenta por organización, y el servidor lo rechazaría
 * igual (409).
 *
 * Patrón combobox de WAI-ARIA con lista de selección múltiple: el foco se
 * queda en el campo, las flechas mueven la opción activa
 * (`aria-activedescendant`) y Enter la marca o desmarca. Las opciones siguen la
 * forma de `SearchAutocomplete`: `div` con `role="option"`, `tabIndex={-1}` y
 * `onMouseDown`, que no roba el foco al campo.
 *
 * Sin `autoFocus`: dentro de un diálogo, Radix ya enfoca el primer control al
 * abrir, que es este campo.
 */

import * as React from "react";
import { Check, Loader2, Search, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { MIN_LONGITUD_BUSQUEDA } from "@/hooks/use-busqueda-global";
import { useBuscarOrganos, type OrganoCandidato } from "@/hooks/use-cuentas";
import { cn, formatNumber } from "@/lib/utils";

export function SelectorOrganos({
  seleccionados,
  onChange,
  cuentaId,
  etiqueta = "Órganos de contratación",
}: {
  seleccionados: readonly string[];
  onChange: (siguientes: string[]) => void;
  /** La cuenta que se edita: sus órganos no cuentan como «de otra cuenta». */
  cuentaId?: number;
  etiqueta?: string;
}) {
  const [texto, setTexto] = React.useState("");
  const id = React.useId();
  const listaId = `${id}-lista`;
  const busqueda = useBuscarOrganos(texto);
  const { candidatos } = busqueda;

  // La opción activa va atada al término con el que se eligió: cada búsqueda
  // nueva empieza por la primera, porque la activa anterior podía no existir
  // ya. Derivado en el render en vez de reiniciado en un efecto.
  const [cursor, setCursor] = React.useState({ q: "", indice: 0 });
  const activo =
    cursor.q === busqueda.q ? Math.min(cursor.indice, Math.max(candidatos.length - 1, 0)) : 0;
  const setActivo = (siguiente: (actual: number) => number) =>
    setCursor({ q: busqueda.q, indice: siguiente(activo) });

  const elegido = (candidato: OrganoCandidato) =>
    seleccionados.includes(candidato.organo_nombre);
  const deEstaCuenta = (candidato: OrganoCandidato) =>
    cuentaId != null && candidato.cuenta_id === cuentaId;
  const deOtraCuenta = (candidato: OrganoCandidato) =>
    candidato.cuenta_id != null && candidato.cuenta_id !== cuentaId;

  function alternar(candidato: OrganoCandidato) {
    if (deOtraCuenta(candidato) || deEstaCuenta(candidato)) return;
    onChange(
      elegido(candidato)
        ? seleccionados.filter((nombre) => nombre !== candidato.organo_nombre)
        : [...seleccionados, candidato.organo_nombre],
    );
  }

  function alPulsarTecla(event: React.KeyboardEvent<HTMLInputElement>) {
    if (candidatos.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActivo((i) => Math.min(i + 1, candidatos.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActivo((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      // Enter marca la opción y no envía el formulario que envuelve al campo.
      event.preventDefault();
      const candidato = candidatos[activo];
      if (candidato) alternar(candidato);
    }
  }

  const estado = !busqueda.activa
    ? `Escribe al menos ${MIN_LONGITUD_BUSQUEDA} letras del nombre del órgano.`
    : busqueda.isError
      ? "No se pudo buscar. Vuelve a intentarlo en un momento."
      : busqueda.pendiente || (busqueda.isFetching && candidatos.length === 0)
        ? "Buscando…"
        : candidatos.length === 0
          ? `Ningún órgano contiene «${busqueda.q}».`
          : `${candidatos.length} órganos. Flechas para moverte, Enter para elegir.`;

  const opcionActiva = candidatos[activo];

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={`${id}-campo`} className="text-sm font-medium">
        {etiqueta}
      </label>

      {seleccionados.length > 0 && (
        <ul aria-label="Órganos elegidos" className="flex flex-wrap gap-1.5">
          {seleccionados.map((nombre) => (
            <li
              key={nombre}
              className="inline-flex max-w-full items-center gap-1 rounded-md border border-primary/30 bg-primary/8 py-0.5 pr-0.5 pl-2 text-xs"
            >
              <span className="truncate">{nombre}</span>
              <button
                type="button"
                onClick={() => onChange(seleccionados.filter((n) => n !== nombre))}
                className="grid h-5 w-5 flex-none place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-3 w-3" aria-hidden="true" />
                <span className="sr-only">Quitar {nombre}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="relative">
        <Search
          className="pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          id={`${id}-campo`}
          role="combobox"
          aria-expanded={candidatos.length > 0}
          aria-controls={listaId}
          aria-autocomplete="list"
          aria-activedescendant={opcionActiva ? `${id}-op-${activo}` : undefined}
          aria-describedby={`${id}-estado`}
          value={texto}
          onChange={(event) => setTexto(event.target.value)}
          onKeyDown={alPulsarTecla}
          placeholder="Ayuntamiento de…, Diputación de…, Consejería de…"
          autoComplete="off"
          maxLength={200}
          className="pl-8"
        />
        {busqueda.isFetching && (
          <Loader2
            className="absolute top-1/2 right-2.5 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground"
            aria-hidden="true"
          />
        )}
      </div>

      <p id={`${id}-estado`} aria-live="polite" className="text-xs text-muted-foreground">
        {estado}
      </p>

      {candidatos.length > 0 && (
        <div
          id={listaId}
          role="listbox"
          aria-multiselectable="true"
          aria-label="Órganos que coinciden"
          className="max-h-64 overflow-y-auto rounded-md border border-border/60"
        >
          {candidatos.map((candidato, indice) => {
            const marcado = elegido(candidato) || deEstaCuenta(candidato);
            const bloqueado = deOtraCuenta(candidato) || deEstaCuenta(candidato);
            return (
              <div
                key={candidato.organo_norm}
                id={`${id}-op-${indice}`}
                role="option"
                aria-selected={marcado}
                aria-disabled={bloqueado || undefined}
                tabIndex={-1}
                onMouseDown={(event) => {
                  // Sin esto el clic se llevaría el foco del campo y el
                  // teclado dejaría de mover la lista.
                  event.preventDefault();
                  alternar(candidato);
                }}
                onMouseEnter={() => setActivo(() => indice)}
                className={cn(
                  "flex cursor-pointer items-start gap-2 border-b border-border/40 px-2.5 py-2 text-sm last:border-b-0",
                  indice === activo && "bg-accent",
                  bloqueado && "cursor-not-allowed opacity-60",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 grid h-4 w-4 flex-none place-items-center rounded border",
                    marcado ? "border-primary bg-primary text-primary-foreground" : "border-border",
                  )}
                  aria-hidden="true"
                >
                  {marcado && <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block leading-tight">{candidato.organo_nombre}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {formatNumber(candidato.expedientes)} expedientes
                    {deEstaCuenta(candidato) && " · ya está en esta cuenta"}
                    {deOtraCuenta(candidato) &&
                      ` · ya está en la cuenta «${candidato.cuenta_nombre ?? "otra"}»`}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
