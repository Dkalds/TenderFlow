"use client";

/**
 * Las dos entradas de la dimensión «afinidad»: palabras clave libres y códigos
 * CPV.
 *
 * Van juntas porque son la misma decisión partida en dos vocabularios —qué
 * texto y qué clasificación te interesan— y comparten el mismo gesto de añadir
 * con Enter y quitar pulsando el chip.
 */

import { X } from "lucide-react";
import { Panel, PanelTitle } from "@/components/console/panel";
import { badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Schemas } from "@/lib/api-types";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { cn, foldText } from "@/lib/utils";
import { isValidCpv } from "../_lib/pesos";

export type CpvNombre = Schemas["CpvNombre"];

const MAX_SUGERENCIAS = 6;

/**
 * Nombre de un CPV según el catálogo de la API, o `null` si no lo conoce.
 *
 * Un código parcial («7226») o más fino que el catálogo («72262000» cuando
 * solo está «72260000») toma el nombre del nivel que lo contiene: se prueba el
 * código y, después, sus prefijos rellenados con ceros, del más largo al más
 * corto. Es la misma caída que aplica la API al rotular un CPV.
 */
export function nombreDeCpv(codigo: string, catalogo: readonly CpvNombre[]): string | null {
  const porCodigo = new Map(catalogo.map((entrada) => [entrada.codigo, entrada.nombre]));
  for (let largo = Math.min(codigo.length, 8); largo >= 2; largo -= 1) {
    const nombre = porCodigo.get(codigo.slice(0, largo).padEnd(8, "0"));
    if (nombre) return nombre;
  }
  return null;
}

/** Entradas del catálogo que casan con lo tecleado, por código o por nombre. */
export function sugerirCpvs(
  tecleado: string,
  catalogo: readonly CpvNombre[],
  yaElegidos: readonly string[],
): CpvNombre[] {
  const busqueda = foldText(tecleado.trim());
  if (!busqueda) return [];
  return catalogo
    .filter(
      (entrada) =>
        !yaElegidos.includes(entrada.codigo) &&
        (entrada.codigo.startsWith(busqueda) || foldText(entrada.nombre).includes(busqueda)),
    )
    .slice(0, MAX_SUGERENCIAS);
}

/**
 * Un valor de la lista que se quita al pulsarlo. Botón de verdad, y no un
 * `Badge` con `onClick`: con teclado no se podía quitar ninguno.
 */
function ChipQuitable({
  valor,
  detalle,
  onRemove,
  codigo,
}: {
  valor: string;
  /** Lo que acompaña al valor sin ser parte de él: el nombre de un CPV. */
  detalle?: string | null;
  onRemove: () => void;
  codigo?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={`Quitar ${valor}${detalle ? `, ${detalle}` : ""}`}
      className={cn(
        badgeVariants({ variant: "secondary" }),
        "h-auto max-w-full gap-1 pr-1.5 text-left transition-colors hover:bg-destructive/10 hover:text-destructive",
      )}
    >
      <span className={cn(codigo && "font-mono")}>{valor}</span>
      {detalle && <span className="min-w-0 truncate text-muted-foreground">{detalle}</span>}
      <X className="h-3 w-3 flex-none" aria-hidden="true" />
    </button>
  );
}

export function KeywordsAfinidadCard({
  keywords,
  kwInput,
  onKwInputChange,
  onAdd,
  onRemove,
}: {
  keywords: string[];
  kwInput: string;
  onKwInputChange: (value: string) => void;
  onAdd: () => void;
  onRemove: (kw: string) => void;
}) {
  return (
    <Panel>
      <PanelTitle title="Palabras clave de afinidad" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Las licitaciones cuyo título o descripción contengan estas palabras suman puntos en la dimensión
        «Afinidad». Se busca la palabra completa. Sin palabras clave ni CPV, esa dimensión no cuenta y su peso se
        reparte entre las demás.
      </p>
      <div className="space-y-3">
        <div className="flex gap-2">
          {/* El placeholder no es un nombre: desaparece al escribir y axe no
              lo cuenta. El título del panel no está asociado al campo. */}
          <Input
            aria-label="Nueva palabra clave de afinidad"
            placeholder="p. ej. consultoría, mantenimiento, SAP…"
            value={kwInput}
            onChange={(e) => onKwInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onAdd();
              }
            }}
            className="flex-1"
          />
          <Button variant="outline" onClick={onAdd} disabled={!kwInput.trim()}>
            Añadir
          </Button>
        </div>
        {keywords.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {keywords.map((kw) => (
              <ChipQuitable key={kw} valor={kw} onRemove={() => onRemove(kw)} />
            ))}
          </div>
        ) : (
          <p className="text-tf-meta text-muted-foreground">
            Sin palabras clave. Puedes escribir varias a la vez, separadas por comas.
          </p>
        )}
      </div>
    </Panel>
  );
}

export function CpvsInteresCard({
  cpvs,
  cpvInput,
  onCpvInputChange,
  onAdd,
  onRemove,
  error,
  catalogo = [],
}: {
  cpvs: string[];
  cpvInput: string;
  onCpvInputChange: (value: string) => void;
  /** Sin argumento añade lo tecleado; con él, ese código (una sugerencia). */
  onAdd: (codigo?: string) => void;
  onRemove: (cpv: string) => void;
  /** Error del esquema sobre la lista (p. ej. más de 50 CPVs). */
  error?: string;
  /** Los CPV que la API sabe nombrar; un código que no esté aquí sigue valiendo. */
  catalogo?: readonly CpvNombre[];
}) {
  const sugerencias = sugerirCpvs(cpvInput, catalogo, cpvs);
  const tecleadoValido = isValidCpv(cpvInput);
  return (
    <Panel>
      <PanelTitle title="CPV de interés" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Códigos CPV en los que trabaja tu equipo. Una licitación con el mismo código puntúa la afinidad máxima; si
        comparte los 4 primeros dígitos (la misma división), un 80 %. Acepta de 4 a 8 dígitos.
      </p>
      <div className="space-y-3">
        <div className="flex gap-2">
          <Input
            id="mp-cpvs"
            aria-label="Nuevo código CPV de interés"
            placeholder="Un código (72000000, 4823…) o parte del nombre"
            value={cpvInput}
            {...ariaCampo("mp-cpvs", error)}
            onChange={(e) => onCpvInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onAdd();
              }
            }}
            className="flex-1"
          />
          <Button variant="outline" onClick={() => onAdd()} disabled={!tecleadoValido}>
            Añadir
          </Button>
        </div>
        <CampoError campoId="mp-cpvs" mensaje={error} />
        {sugerencias.length > 0 && (
          <ul aria-label="CPV que coinciden" className="space-y-1">
            {sugerencias.map((sugerencia) => (
              <li key={sugerencia.codigo}>
                <button
                  type="button"
                  onClick={() => onAdd(sugerencia.codigo)}
                  aria-label={`Añadir ${sugerencia.codigo}, ${sugerencia.nombre}`}
                  className="flex min-h-6 w-full items-baseline gap-2 rounded-md px-2 py-1 text-left text-tf-meta transition-colors hover:bg-primary/5"
                >
                  <span className="font-mono">{sugerencia.codigo}</span>
                  <span className="min-w-0 truncate text-muted-foreground">{sugerencia.nombre}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {cpvInput.trim() !== "" && !tecleadoValido && sugerencias.length === 0 && (
          <p className="text-tf-meta text-destructive">
            Ningún CPV con nombre coincide. Para añadir otro, escribe su código: entre 4 y 8 dígitos, sin letras ni
            guiones.
          </p>
        )}
        {cpvs.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {cpvs.map((cpv) => (
              <ChipQuitable
                key={cpv}
                valor={cpv}
                detalle={nombreDeCpv(cpv, catalogo)}
                codigo
                onRemove={() => onRemove(cpv)}
              />
            ))}
          </div>
        ) : (
          <p className="text-tf-meta text-muted-foreground">
            Sin CPV configurados: la afinidad solo mira tus palabras clave.
          </p>
        )}
      </div>
    </Panel>
  );
}
