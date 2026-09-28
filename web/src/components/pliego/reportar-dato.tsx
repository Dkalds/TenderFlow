"use client";

import * as React from "react";
import { Flag, Loader2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { PanelError } from "@/components/console/panel";
import { Textarea } from "@/components/ui/textarea";
import {
  DESTINO_COLA,
  TIPOS_REPORTE,
  type ReporteDatoResult,
  type TipoReporte,
  useReportarDato,
} from "@/hooks/use-reportar-dato";
import { ETIQUETA_CAMPO } from "@/components/ui/field";
import { getErrorMessage } from "@/lib/query-feedback";
import { cn, formatDateTime } from "@/lib/utils";

/**
 * F6.2 — «este dato está mal», desde la ficha.
 *
 * Tras enviar, el diálogo no se cierra con un «gracias» sin contenido: dice a
 * qué revisión ha llegado el reporte (la `cola` que devuelve la API) y cuándo
 * quedó registrado, que es el estado que el usuario puede ver hoy.
 */
const MAX_COMENTARIO = 2000;

export function ReportarDatoBoton({
  licitacionId,
  className,
}: {
  licitacionId: string;
  className?: string;
}) {
  const [abierto, setAbierto] = React.useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setAbierto(true)}
        className={className ?? buttonVariants({ variant: "outline", size: "sm" })}
        aria-haspopup="dialog"
      >
        <Flag className="h-3 w-3" aria-hidden="true" />
        Reportar dato
      </button>
      {abierto && (
        <ReportarDatoDialog licitacionId={licitacionId} onClose={() => setAbierto(false)} />
      )}
    </>
  );
}

function ReportarDatoDialog({
  licitacionId,
  onClose,
}: {
  licitacionId: string;
  onClose: () => void;
}) {
  const reportar = useReportarDato(licitacionId);
  const [tipo, setTipo] = React.useState<TipoReporte | null>(null);
  const [comentario, setComentario] = React.useState("");
  const [acuse, setAcuse] = React.useState<ReporteDatoResult | null>(null);
  const idComentario = React.useId();

  const enviar = (event: React.FormEvent) => {
    event.preventDefault();
    if (!tipo) return;
    reportar.mutate(
      { tipo, comentario: comentario.trim() || null },
      { onSuccess: (resultado) => setAcuse(resultado) },
    );
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="mx-4 w-full max-w-md">
        <DialogTitle>Reportar un dato incorrecto</DialogTitle>
        {acuse ? (
          <div role="status" className="space-y-3 text-tf-body">
            <p>
              Reporte recibido: <strong>{TIPOS_REPORTE[acuse.tipo as TipoReporte] ?? acuse.tipo}</strong>.
            </p>
            <DialogDescription>
              Ha llegado a {DESTINO_COLA[acuse.cola] ?? "la cola de revisión"} el{" "}
              {formatDateTime(acuse.created_at)}. Quien lo revise corregirá el expediente si procede.
            </DialogDescription>
            <div className="flex justify-end">
              <Button size="sm" onClick={onClose}>Cerrar</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={enviar} className="space-y-4">
            <DialogDescription>
              Dinos qué está mal en este expediente. Cada tipo llega a la revisión que le corresponde.
            </DialogDescription>
            <fieldset className="space-y-1.5">
              <legend className={cn("mb-1.5", ETIQUETA_CAMPO)}>Qué dato está mal</legend>
              {(Object.entries(TIPOS_REPORTE) as [TipoReporte, string][]).map(([valor, etiqueta]) => (
                <label key={valor} className="flex cursor-pointer items-center gap-2 text-tf-body">
                  <input
                    type="radio"
                    name="tipo-reporte"
                    value={valor}
                    checked={tipo === valor}
                    onChange={() => setTipo(valor)}
                    className="accent-primary"
                    // El `<label>` que lo envuelve ya le da nombre, pero la
                    // regla es estática y no ve `{etiqueta}`; mismo patrón que
                    // `pursuits/adjudicacion-detectada.tsx`.
                    aria-label={etiqueta}
                  />
                  {etiqueta}
                </label>
              ))}
            </fieldset>
            <div className="space-y-1.5">
              <label htmlFor={idComentario} className={ETIQUETA_CAMPO}>
                Comentario <span className="font-normal text-muted-foreground">(opcional)</span>
              </label>
              <Textarea
                id={idComentario}
                value={comentario}
                maxLength={MAX_COMENTARIO}
                onChange={(e) => setComentario(e.target.value)}
                placeholder="p. ej. la CCAA correcta es Galicia…"
                rows={3}
              />
            </div>
            {reportar.error && (
              <PanelError
                variant="inline"
                title="No se pudo enviar el reporte"
                error={reportar.error}
                message={getErrorMessage(reportar.error, "accion")}
                className="py-0"
              />
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={onClose}>
                Cancelar
              </Button>
              <Button type="submit" size="sm" disabled={!tipo || reportar.isPending}>
                {reportar.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                Enviar reporte
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
