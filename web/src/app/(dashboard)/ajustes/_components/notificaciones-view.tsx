"use client";

import { useState } from "react";
import { Panel, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import {
  usePreferenciasNotificacion,
  useGuardarPreferencias,
  type PreferenciaNotificacion,
} from "@/hooks/use-cuenta";

/**
 * Notificaciones — qué avisa, por dónde y cada cuánto (C2.7).
 *
 * Ninguna tabla las modelaba hasta `v117`, así que «no me mandes esto» no tenía
 * dónde guardarse y cada canal habría acabado inventando el suyo — que es como
 * se llega a tener el mismo ajuste en tres pantallas con tres valores distintos.
 *
 * La ausencia de fila significa **el valor por defecto**, no `off`: apagar por
 * omisión es la clase de decisión que hace que nadie se entere de nada y nadie
 * sepa por qué. Por eso la tabla se pinta a partir del contrato del backend y no
 * de lo que haya guardado.
 */

const FRECUENCIAS = [
  { valor: "immediate", etiqueta: "Al momento" },
  { valor: "daily", etiqueta: "Resumen diario" },
  { valor: "off", etiqueta: "Nunca" },
] as const;

const CANALES: Record<string, string> = {
  in_app: "En la aplicación",
  email: "Correo",
  webhook: "Webhook",
};

function clave(item: PreferenciaNotificacion): string {
  return `${item.tipo}|${item.canal}`;
}

export default function NotificacionesView() {
  const { data, isLoading, error, refetch } = usePreferenciasNotificacion();
  const guardar = useGuardarPreferencias();
  const [cambios, setCambios] = useState<Record<string, string>>({});

  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar las preferencias"
        detail={error instanceof Error ? error.message : undefined}
        onRetry={() => void refetch()}
      />
    );
  }
  if (isLoading) return <PanelLoading />;

  const items = ((data?.items ?? []) as PreferenciaNotificacion[]).map((item) => ({
    ...item,
    frecuencia: cambios[clave(item)] ?? item.frecuencia,
  }));
  const sucio = Object.keys(cambios).length > 0;

  return (
    <Panel>
      <PanelTitle
        title="Avisos"
        hint="Lo que no toques se queda como está por defecto"
        actions={
          <Button
            size="sm"
            disabled={!sucio || guardar.isPending}
            onClick={() =>
              guardar.mutate(items, {
                onSuccess: () => setCambios({}),
              })
            }
          >
            {guardar.isPending ? "Guardando…" : "Guardar"}
          </Button>
        }
      />
      <table className="w-full text-[11.5px]">
        <caption className="sr-only">Preferencias de notificación por tipo y canal</caption>
        <thead>
          <tr className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <th scope="col" className="py-1.5">
              Aviso
            </th>
            <th scope="col" className="py-1.5">
              Canal
            </th>
            <th scope="col" className="py-1.5">
              Cuándo
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {items.map((item) => (
            <tr key={clave(item)}>
              <td className="py-2 pr-3 font-medium">{item.tipo}</td>
              <td className="py-2 pr-3 text-muted-foreground">
                {CANALES[item.canal] ?? item.canal}
              </td>
              <td className="py-2">
                <label className="sr-only" htmlFor={`frec-${clave(item)}`}>
                  Frecuencia de {item.tipo} por {CANALES[item.canal] ?? item.canal}
                </label>
                <select
                  id={`frec-${clave(item)}`}
                  value={item.frecuencia}
                  onChange={(event) =>
                    setCambios((previo) => ({ ...previo, [clave(item)]: event.target.value }))
                  }
                  className="rounded-md border border-border/60 bg-background px-2 py-1 text-[11.5px]"
                >
                  {FRECUENCIAS.map((opcion) => (
                    <option key={opcion.valor} value={opcion.valor}>
                      {opcion.etiqueta}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {guardar.isError && (
        <p className="mt-3 text-[11px] text-destructive">No se pudieron guardar los cambios.</p>
      )}
    </Panel>
  );
}
