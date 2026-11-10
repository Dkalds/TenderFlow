"use client";

/**
 * El permiso de cita de un adjunto (ADR-040, CU-36).
 *
 * Quien escribe puede dejar que el Investigador y el guion de la oferta citen
 * extractos de un fichero. Es por fichero porque en la misma oportunidad
 * conviven la memoria técnica y el currículum de alguien. Activarlo va en dos
 * pasos dentro de la fila, y el segundo dice lo que implica antes de que
 * ocurra; quitarlo es inmediato, porque es la dirección segura.
 */
import * as React from "react";
import { toast } from "@/lib/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useMarcarCitable } from "@/hooks/use-pursuit-adjuntos";
import { estadoDeCita, motivoNoCitable, type Adjunto, type PoliticaAdjuntos } from "@/lib/adjuntos";

/**
 * El permiso de cita de un fichero y cómo va su lectura.
 *
 * Quien solo lee ve el estado, sin interruptor. Un fichero del que no se puede
 * leer texto (una imagen, una hoja de Excel) o que pasa del tope lo dice en vez
 * de ofrecer un interruptor que el servidor va a rechazar.
 */
export function PermisoDeCita({
  pursuitId,
  adjunto,
  puedeCambiarlo,
  politica,
}: {
  pursuitId: number;
  adjunto: Adjunto;
  puedeCambiarlo: boolean;
  politica: PoliticaAdjuntos | undefined;
}) {
  const marcar = useMarcarCitable(pursuitId);
  const [confirmando, setConfirmando] = React.useState(false);
  const idInterruptor = React.useId();
  const estado = estadoDeCita(adjunto);

  // Con las citas apagadas en el entorno solo queda poder quitar un permiso
  // que ya estuviera dado.
  const citasActivas = (politica?.indexado_max_documentos ?? 0) > 0;
  if (!adjunto.indexable && !citasActivas) return null;
  if (!puedeCambiarlo && !estado) return null;
  const motivo = !adjunto.indexable && politica ? motivoNoCitable(adjunto, politica) : null;

  const cambiar = (citable: boolean) =>
    marcar.mutate(
      { attachmentId: adjunto.id, citable },
      {
        onSuccess: () =>
          toast.success(
            citable
              ? `«${adjunto.filename}» se está leyendo para poder citarse`
              : `«${adjunto.filename}» ya no se cita y su texto se ha borrado`,
          ),
        onSettled: () => setConfirmando(false),
      },
    );

  return (
    <div className="basis-full text-tf-meta">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {puedeCambiarlo && !motivo && (
          <>
            <Switch
              id={idInterruptor}
              checked={adjunto.indexable}
              disabled={marcar.isPending || confirmando}
              onCheckedChange={(citable) => (citable ? setConfirmando(true) : cambiar(false))}
              aria-label={`Permitir que se cite ${adjunto.filename}`}
            />
            <label htmlFor={idInterruptor} className="cursor-pointer">
              Permitir que se cite
            </label>
          </>
        )}
        {estado && (
          <Badge variant={estado.tono} size="sm">
            {estado.etiqueta}
          </Badge>
        )}
        {estado?.detalle && <span className="text-muted-foreground">{estado.detalle}</span>}
        {puedeCambiarlo && motivo && <span className="text-muted-foreground">No se puede citar: {motivo}</span>}
      </div>
      {confirmando && (
        <div role="group" aria-label="Confirmar el permiso de cita" className="mt-1.5 space-y-1.5">
          <p className="text-muted-foreground max-w-prose">
            El Investigador y el guion de la oferta podrán enseñar extractos literales de este fichero a cualquier
            persona de tu organización, y a nadie de fuera. Para buscarlos se guarda su texto, que se borra si quitas
            el permiso o retiras el fichero.
          </p>
          <div className="flex items-center gap-1.5">
            <Button type="button" size="sm" disabled={marcar.isPending} onClick={() => cambiar(true)}>
              Permitir
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmando(false)}>
              Cancelar
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
