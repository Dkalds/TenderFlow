"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { numeroDeTexto } from "@/lib/forms/valores";
import { cn } from "@/lib/utils";
import type { Pursuit, PursuitStatus, UpdatePursuitInput } from "@/hooks/use-pursuits";
import type { Resultado } from "../_lib/flujo";

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

const TODOS: readonly Resultado[] = ["won", "lost", "withdrawn"];

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
 *
 * `resultados` son los que el backend acepta desde el estado actual
 * (`_lib/flujo.ts`): «Ganada» y «Perdida» solo salen de «Presentada», así que
 * desde cualquier otra fase lo único que se ofrece es retirarla. «Ganada» pide
 * el importe adjudicado y no un motivo: el backend exige importe o
 * justificación, y la lista de D37 son causas de pérdida.
 */
export function DialogoCierre({
  pursuit,
  resultados = TODOS,
  onCancelar,
  onConfirmar,
}: {
  pursuit: Pursuit | null;
  resultados?: readonly Resultado[];
  onCancelar: () => void;
  onConfirmar: (cambios: UpdatePursuitInput & { status: PursuitStatus }) => void;
}) {
  // Sin valor por defecto de conveniencia: «Perdida» y «Precio» son la
  // combinación más frecuente y ponerlas preseleccionadas haría que cerrar sea
  // dar a Aceptar, que es exactamente como se ensucia el informe de pérdidas.
  // Con un único resultado posible no hay nada que elegir, y sí se marca.
  const [resultado, setResultado] = React.useState<Resultado | null>(
    resultados.length === 1 ? resultados[0] : null,
  );
  const [motivo, setMotivo] = React.useState<string>("");
  const [importe, setImporte] = React.useState<string>("");
  const importeId = React.useId();

  if (!pursuit) return null;

  const importeNumero = numeroDeTexto(importe);
  const importeValido = importeNumero != null && importeNumero > 0;
  const listo =
    resultado === "won" ? importeValido : resultado != null && motivo !== "";
  const soloRetirar = resultados.length === 1 && resultados[0] === "withdrawn";
  const opciones = RESULTADOS.filter((opcion) => resultados.includes(opcion.key));

  const confirmar = () => {
    if (resultado === "won") {
      onConfirmar({
        status: "won",
        outcome: "won",
        awarded_amount_eur: importeNumero,
        expected_version: pursuit.version,
      });
      return;
    }
    onConfirmar({
      status: resultado as Resultado,
      outcome: resultado === "withdrawn" ? "cancelled" : "lost",
      outcome_reason_code: motivo as UpdatePursuitInput["outcome_reason_code"],
      expected_version: pursuit.version,
    });
  };

  return (
    <Dialog open onOpenChange={(abierto) => (abierto ? undefined : onCancelar())}>
      <DialogContent className="w-[440px] p-5">
        <DialogTitle>{soloRetirar ? "Retirar la oportunidad" : "Cerrar la oportunidad"}</DialogTitle>
        <DialogDescription className="mt-1 mb-4">
          {pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}
        </DialogDescription>

        {soloRetirar ? (
          <p className="text-muted-foreground mb-4 text-tf-meta leading-[1.45]">
            «Ganada» y «Perdida» solo se registran desde «Presentada». Desde esta fase, cerrar es
            retirarla.
          </p>
        ) : (
          <fieldset className="mb-4">
            <legend className="text-muted-foreground mb-1.5 font-mono text-tf-micro font-semibold tracking-wider uppercase">
              Resultado
            </legend>
            <div className="flex gap-1.5">
              {opciones.map((opcion) => (
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
        )}

        {resultado === "won" ? (
          <div className="mb-4">
            <label
              htmlFor={importeId}
              className="text-muted-foreground mb-1.5 block font-mono text-tf-micro font-semibold tracking-wider uppercase"
            >
              Importe adjudicado (€)
            </label>
            <Input
              id={importeId}
              inputMode="decimal"
              value={importe}
              onChange={(event) => setImporte(event.target.value)}
              placeholder="Ej. 2080000"
            />
          </div>
        ) : (
          // Un `<label>` aquí no tendría control nativo que envolver: el
          // disparador de Radix es un botón, así que el nombre accesible va en
          // él y esto es sólo el rótulo visible.
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
        )}

        <div className="flex items-center gap-2">
          <p className="text-muted-foreground flex-1 text-tf-micro leading-[1.4]">
            {resultado === "won"
              ? "Sin importe, lo ganado no suma en el valor adjudicado."
              : "El motivo alimenta el informe de pérdidas por causa."}
          </p>
          <Button variant="outline" size="sm" onClick={onCancelar}>
            Cancelar
          </Button>
          {/* «Cerrar» a secas no: la X del diálogo ya se anuncia así, y dos
              botones con el mismo nombre y sentidos opuestos es justo lo que
              oye quien navega con lector de pantalla. */}
          <Button size="sm" disabled={!listo} onClick={confirmar}>
            {soloRetirar ? "Retirar" : "Confirmar cierre"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
