"use client";

import * as React from "react";
import { ArrowRight, Check } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import { usePursuitChecklist } from "@/hooks/use-pursuit-checklist";
import { resumenKit, usePursuitKit } from "@/hooks/use-pursuit-kit";
import {
  useUpdatePursuit,
  type Pursuit,
  type PursuitStatus,
  type UpdatePursuitInput,
} from "@/hooks/use-pursuits";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { DialogoCierre } from "../../_components/dialogo-cierre";
import { resultadosPermitidos } from "../../_lib/flujo";
import { salidaDeFase } from "../../_lib/salida-fase";

/**
 * Lo que falta para salir de la fase actual, y el único botón que la mueve.
 *
 * Los pasos salen de datos reales (`_lib/salida-fase.ts`). El kit y el
 * contraste del pliego se piden con los mismos hooks que sus paneles de esta
 * misma pestaña, así que comparten caché y no añaden una petición.
 *
 * Avanzar es un PATCH de `status` con `expected_version`, igual que arrastrar
 * en el tablero: si alguien del equipo la movió mientras la ficha estaba
 * abierta, el 409 lo dice en vez de pisar su cambio.
 */
export function SalidaDeFase({ pursuit }: { pursuit: Pursuit }) {
  const kit = usePursuitKit(pursuit.id);
  const contraste = usePursuitChecklist(pursuit.id);
  const actualizar = useUpdatePursuit(pursuit.id);
  const [cerrando, setCerrando] = React.useState(false);
  const tituloId = React.useId();

  const salida = salidaDeFase(pursuit, {
    kit: kit.data ? resumenKit(kit.data) : undefined,
    contraste: contraste.data
      ? {
          total_requisitos: contraste.data.total_requisitos,
          desconocido: contraste.data.desconocido,
        }
      : undefined,
  });

  const aplicar = (cambios: UpdatePursuitInput & { status: PursuitStatus }) => {
    actualizar.mutate(cambios, {
      onSuccess: () => toast.success(`Pasa a ${statusLabel(cambios.status)}`),
      onError: (error) =>
        toast.error(
          error instanceof ApiError && error.status === 409
            ? "Alguien del equipo la cambió mientras la tenías abierta"
            : "No se pudo mover la oportunidad",
          { description: error instanceof Error ? error.message : undefined },
        ),
    });
  };

  const accion = salida.accion;
  const bloqueo = accion?.tipo === "avanzar" ? accion.bloqueo : null;
  // Retirar cabe desde cualquier fase abierta, pero no se duplica: cuando la
  // acción principal ya abre el diálogo, ese diálogo lo ofrece.
  const retirarAparte = accion?.tipo === "avanzar" && resultadosPermitidos(pursuit).length > 0;

  return (
    <section
      aria-labelledby={tituloId}
      className="border-primary/30 bg-primary/[0.05] rounded-xl border px-4 py-3.5"
    >
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id={tituloId} className="text-tf-body font-semibold">
          {salida.titulo}
        </h2>
        <div className="flex-1" />
        <span className="tf-tnum text-muted-foreground font-mono text-tf-micro font-medium">
          {salida.hechos} de {salida.pasos.length}
        </span>
      </div>

      <ul className="mb-3 flex flex-col gap-1.5">
        {salida.pasos.map((paso) => (
          <li key={paso.clave} className="flex items-start gap-2">
            <span
              aria-hidden="true"
              className={cn(
                "mt-0.5 grid h-3.5 w-3.5 flex-none place-items-center rounded-full",
                paso.hecho === true
                  ? "bg-success text-success-foreground"
                  : paso.hecho === false
                    ? "border-border/70 border-[1.5px]"
                    : "border-border/70 border-[1.5px] border-dashed",
              )}
            >
              {paso.hecho === true ? <Check className="h-2.5 w-2.5" /> : null}
            </span>
            <span className="min-w-0 flex-1">
              <span
                className={cn(
                  "text-tf-body leading-[1.4]",
                  paso.hecho === true && "text-muted-foreground line-through",
                )}
              >
                {paso.texto}
              </span>
              {paso.requerido && paso.hecho !== true ? (
                <span className="text-muted-foreground text-tf-micro"> · obligatorio</span>
              ) : null}
              {paso.detalle ? (
                <span className="text-muted-foreground block text-tf-micro leading-[1.35]">
                  {paso.detalle}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-2">
        {accion ? (
          <Button
            size="sm"
            disabled={bloqueo != null || actualizar.isPending}
            onClick={() =>
              accion.tipo === "cerrar"
                ? setCerrando(true)
                : aplicar({ status: accion.destino, expected_version: pursuit.version })
            }
          >
            {accion.tipo === "avanzar" ? (
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            ) : null}
            {accion.etiqueta}
          </Button>
        ) : null}
        {retirarAparte ? (
          <Button variant="ghost" size="sm" onClick={() => setCerrando(true)}>
            Retirar…
          </Button>
        ) : null}
        <p className="text-muted-foreground min-w-[14rem] flex-1 text-tf-micro leading-[1.4]">
          {bloqueo ?? salida.nota}
        </p>
      </div>

      {cerrando ? (
        <DialogoCierre
          pursuit={pursuit}
          resultados={resultadosPermitidos(pursuit)}
          onCancelar={() => setCerrando(false)}
          onConfirmar={(cambios) => {
            setCerrando(false);
            aplicar(cambios);
          }}
        />
      ) : null}
    </section>
  );
}
