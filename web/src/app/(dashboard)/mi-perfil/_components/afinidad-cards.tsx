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
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { cn } from "@/lib/utils";
import { isValidCpv } from "../_hooks/use-perfil-scoring";

/**
 * Un valor de la lista que se quita al pulsarlo. Botón de verdad, y no un
 * `Badge` con `onClick`: con teclado no se podía quitar ninguno.
 */
function ChipQuitable({ valor, onRemove, codigo }: { valor: string; onRemove: () => void; codigo?: boolean }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={`Quitar ${valor}`}
      className={cn(
        badgeVariants({ variant: "secondary" }),
        "gap-1 pr-1.5 transition-colors hover:bg-destructive/10 hover:text-destructive",
        codigo && "font-mono",
      )}
    >
      {valor}
      <X className="h-3 w-3" aria-hidden="true" />
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
            Sin palabras clave. Si tampoco hay CPV, la afinidad no cuenta en la puntuación.
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
}: {
  cpvs: string[];
  cpvInput: string;
  onCpvInputChange: (value: string) => void;
  onAdd: () => void;
  onRemove: (cpv: string) => void;
  /** Error del esquema sobre la lista (p. ej. más de 50 CPVs). */
  error?: string;
}) {
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
            placeholder="p. ej. 72000000, 4823…"
            value={cpvInput}
            inputMode="numeric"
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
          <Button variant="outline" onClick={onAdd} disabled={!isValidCpv(cpvInput)}>
            Añadir
          </Button>
        </div>
        <CampoError campoId="mp-cpvs" mensaje={error} />
        {cpvInput.trim() !== "" && !isValidCpv(cpvInput) && (
          <p className="text-tf-meta text-destructive">Un CPV son entre 4 y 8 dígitos, sin letras ni guiones.</p>
        )}
        {cpvs.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {cpvs.map((cpv) => (
              <ChipQuitable key={cpv} valor={cpv} codigo onRemove={() => onRemove(cpv)} />
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
