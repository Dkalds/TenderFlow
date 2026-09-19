"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { Pursuit, PursuitStatus, UpdatePursuitInput } from "@/hooks/use-pursuits";

type Resultado = "won" | "lost" | "withdrawn";

const RESULTADOS: { key: Resultado; etiqueta: string; clase: string }[] = [
  { key: "won", etiqueta: "Ganada", clase: "border-[hsl(var(--success))] bg-success/14 text-success" },
  {
    key: "lost",
    etiqueta: "Perdida",
    clase: "border-destructive bg-destructive/12 text-destructive",
  },
  {
    key: "withdrawn",
    etiqueta: "Retirada",
    clase: "border-[hsl(var(--warning))] bg-warning/14 text-warning",
  },
];

/** La lista cerrada de D37, tal cual la acepta `outcome_reason_code`. */
const MOTIVOS = [
  { key: "precio", etiqueta: "Precio" },
  { key: "tecnica", etiqueta: "Valoración técnica" },
  { key: "solvencia", etiqueta: "Solvencia" },
  { key: "plazo", etiqueta: "Plazo" },
  { key: "desierto_o_anulado", etiqueta: "Desierto o anulado" },
  { key: "no_presentada", etiqueta: "No presentada" },
  { key: "otro", etiqueta: "Otro" },
] as const;

/**
 * Cerrar no es mover.
 *
 * Las otras cinco columnas son un cambio de estado y nada más, así que soltar
 * una tarjeta en ellas basta. «Cerradas» esconde tres resultados distintos y
 * además es donde nace el informe de pérdidas por causa: soltar ahí sin
 * preguntar obligaría a elegir uno por el usuario, y el que se eligiera sería
 * el que ensuciaría el informe.
 */
export function DialogoCierre({
  pursuit,
  onCancelar,
  onConfirmar,
}: {
  pursuit: Pursuit | null;
  onCancelar: () => void;
  onConfirmar: (cambios: UpdatePursuitInput & { status: PursuitStatus }) => void;
}) {
  // Sin valor por defecto de conveniencia: «Perdida» y «Precio» son la
  // combinación más frecuente y ponerlas preseleccionadas haría que cerrar sea
  // dar a Aceptar, que es exactamente como se ensucia el informe de pérdidas.
  const [resultado, setResultado] = React.useState<Resultado | null>(null);
  const [motivo, setMotivo] = React.useState<string>("");

  if (!pursuit) return null;

  const listo = resultado != null && motivo !== "";

  return (
    <Dialog open onOpenChange={(abierto) => (abierto ? undefined : onCancelar())}>
      <DialogContent className="w-[440px] p-5">
        <DialogTitle>Cerrar la oportunidad</DialogTitle>
        <DialogDescription className="mt-1 mb-4">
          {pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}
        </DialogDescription>

        <fieldset className="mb-4">
          <legend className="text-muted-foreground mb-1.5 font-mono text-tf-micro font-semibold tracking-wider uppercase">
            Resultado
          </legend>
          <div className="flex gap-1.5">
            {RESULTADOS.map((opcion) => (
              <button
                key={opcion.key}
                type="button"
                aria-pressed={resultado === opcion.key}
                onClick={() => setResultado(opcion.key)}
                className={cn(
                  "h-8 flex-1 rounded-md border text-tf-body font-semibold transition-colors",
                  resultado === opcion.key
                    ? opcion.clase
                    : "border-input text-muted-foreground hover:text-foreground",
                )}
              >
                {opcion.etiqueta}
              </button>
            ))}
          </div>
        </fieldset>

        {/* Un `<label>` aquí no tendría control nativo que envolver: el
            disparador de Radix es un botón, así que el nombre accesible va en
            él y esto es sólo el rótulo visible. */}
        <div className="mb-4">
          <span className="text-muted-foreground mb-1.5 block font-mono text-tf-micro font-semibold tracking-wider uppercase">
            Motivo
          </span>
          <Select value={motivo} onValueChange={setMotivo}>
            <SelectTrigger aria-label="Motivo del cierre">
              <SelectValue placeholder="Elige un motivo" />
            </SelectTrigger>
            <SelectContent>
              {MOTIVOS.map((opcion) => (
                <SelectItem key={opcion.key} value={opcion.key}>
                  {opcion.etiqueta}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2">
          <p className="text-muted-foreground flex-1 text-tf-micro leading-[1.4]">
            El motivo alimenta el informe de pérdidas por causa.
          </p>
          <Button variant="outline" size="sm" onClick={onCancelar}>
            Cancelar
          </Button>
          <Button
            size="sm"
            disabled={!listo}
            onClick={() =>
              onConfirmar({
                status: resultado as Resultado,
                outcome: resultado === "withdrawn" ? "cancelled" : (resultado as "won" | "lost"),
                outcome_reason_code: motivo as UpdatePursuitInput["outcome_reason_code"],
                expected_version: pursuit.version,
              })
            }
          >
            Cerrar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
