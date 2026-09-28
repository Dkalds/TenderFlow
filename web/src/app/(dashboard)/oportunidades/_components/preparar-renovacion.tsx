"use client";

/**
 * F4.3 — «Preparar renovación» de un contrato en cartera.
 *
 * Crea la oportunidad de la relicitación, enlazada al contrato
 * (`POST /pursuits/cartera/{id}/renovacion`). Pide el expediente de la
 * relicitación porque la oportunidad es sobre **ese** expediente: el del
 * contrato vigente ya tiene la suya, la ganada, y la API lo rechaza.
 * Idempotente: un segundo intento devuelve la misma oportunidad.
 */
import * as React from "react";
import { RefreshCcw } from "lucide-react";
import { toast } from "sonner";
import { PanelError } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { usePrepararRenovacion } from "@/hooks/use-cartera";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/query-feedback";

export function PrepararRenovacion({
  carteraId,
  licitacionVigente,
  titulo,
}: {
  carteraId: number;
  licitacionVigente: string;
  titulo: string;
}) {
  const [abierto, setAbierto] = React.useState(false);
  const [expediente, setExpediente] = React.useState("");
  const preparar = usePrepararRenovacion();
  const inputId = React.useId();

  const destino = expediente.trim();
  const esElVigente = destino !== "" && destino === licitacionVigente;
  const error = preparar.error;
  const mensajeError =
    error instanceof ApiError && error.status === 422
      ? error.message
      : error instanceof ApiError && error.status === 404
        ? "Ese contrato ya no está en la cartera de tu organización."
        : error
          ? getErrorMessage(error, "accion")
          : null;

  const enviar = (event: React.FormEvent) => {
    event.preventDefault();
    if (!destino || esElVigente) return;
    preparar.mutate(
      { carteraId, licitacionId: destino },
      {
        onSuccess: (resultado) => {
          setAbierto(false);
          toast.success(
            resultado.creada
              ? "Oportunidad de renovación creada"
              : "Este contrato ya tenía su oportunidad de renovación",
          );
        },
      },
    );
  };

  return (
    <>
      <Button size="sm" variant="outline" className="mt-1" onClick={() => setAbierto(true)}>
        <RefreshCcw aria-hidden="true" />
        Preparar renovación
      </Button>
      <Dialog open={abierto} onOpenChange={setAbierto}>
        <DialogContent className="max-w-md">
          <DialogTitle>Preparar la renovación</DialogTitle>
          <DialogDescription>
            Crea la oportunidad de la relicitación de «{titulo}» en «identificada», con una nota que
            enlaza este contrato. Indica el expediente de la relicitación publicada.
          </DialogDescription>
          <form onSubmit={enviar} className="space-y-3">
            <Field
              label="Expediente de la relicitación"
              htmlFor={inputId}
              error={
                esElVigente ? "Ese es el expediente del contrato vigente: la renovación es el siguiente." : null
              }
            >
              <Input
                id={inputId}
                value={expediente}
                onChange={(e) => setExpediente(e.target.value)}
                placeholder="Expediente nuevo…"
              />
            </Field>
            {mensajeError && (
              <PanelError
                variant="inline"
                className="py-0"
                title="No se pudo preparar la renovación"
                message={mensajeError}
                error={error}
              />
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setAbierto(false)}>
                Cancelar
              </Button>
              <Button type="submit" size="sm" disabled={!destino || esElVigente || preparar.isPending}>
                {preparar.isPending ? "Creando…" : "Crear oportunidad"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
