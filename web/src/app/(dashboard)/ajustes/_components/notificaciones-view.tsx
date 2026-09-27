"use client";

/**
 * Preferencias de notificación (C2.7).
 *
 * Ninguna tabla las modelaba (hecho 13 del plan) y el despachador de eventos las
 * necesita para saber a quién avisar y por dónde. `v118` creó la tabla; esta es
 * su pantalla.
 *
 * **El catálogo de tipos lo sirve el backend**, no esta pantalla. Una lista de
 * avisos hardcodeada aquí se queda atrás en cuanto nace uno nuevo: el usuario
 * deja de poder configurarlo y nada falla (ADR-014, invariante 3).
 *
 * Un ajuste que nadie ha tocado se pinta con el **defecto de su canal**, que
 * también viene del backend. Pintarlo como «off» sería mentir: el aviso sí
 * llega, y el usuario creería haberlo desactivado.
 */

import * as React from "react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Field } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type NotificationPreference,
  useGuardarPreferencias,
  usePreferencias,
} from "@/hooks/use-ajustes";

const CANALES = [
  { canal: "in_app", label: "En la aplicación" },
  { canal: "email", label: "Correo" },
  { canal: "webhook", label: "Webhook" },
] as const;

const FRECUENCIAS = [
  { value: "immediate", label: "Al momento" },
  { value: "daily", label: "Resumen diario" },
  { value: "off", label: "No avisar" },
] as const;

export default function NotificacionesView() {
  const { data, isLoading, error, refetch } = usePreferencias();
  const guardar = useGuardarPreferencias();

  const tipos = data?.tipos ?? [];

  /**
   * Frecuencia efectiva: la fijada, o el defecto del canal.
   *
   * `data` entero como dependencia y no `items`/`defaults` por separado: un
   * `?? []` crea un array nuevo en cada render, así que dependencias derivadas
   * cambiarían siempre y la memoización no memoizaría nada.
   */
  const frecuenciaDe = React.useCallback(
    (tipo: string, canal: string): string => {
      const fijada = data?.items?.find((p) => p.tipo === tipo && p.canal === canal);
      return fijada?.frecuencia ?? data?.defaults?.[canal] ?? "off";
    },
    [data],
  );

  const cambiar = (tipo: string, canal: string, frecuencia: string) => {
    // Se manda **solo lo que el usuario tocó**: el PUT del backend añade o
    // pisa, no reemplaza el conjunto, así que enviar la tabla entera
    // materializaría como decisión explícita cada defecto que nadie eligió.
    guardar.mutate([
      { tipo, canal, frecuencia, organization_id: null } as NotificationPreference,
    ]);
  };

  if (isLoading) return <Skeleton className="h-64 w-full rounded-xl" />;
  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar tus preferencias"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (tipos.length === 0) {
    return (
      <PanelEmpty
        title="No hay avisos configurables"
        hint="Cuando haya un tipo de aviso disponible, aparecerá aquí con sus canales."
      />
    );
  }

  return (
    <Panel>
      <PanelTitle title="Qué avisos quieres recibir" />
      <ul className="space-y-3">
        {tipos.map((t) => (
          <li key={t.tipo} className="rounded-md border border-border/60 p-3">
            <p className="text-tf-body font-medium">{t.label}</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {CANALES.map(({ canal, label }) => {
                const id = `${t.tipo}-${canal}`;
                return (
                  <Field key={canal} label={label} htmlFor={id}>
                    <Select
                      value={frecuenciaDe(t.tipo, canal)}
                      disabled={guardar.isPending}
                      onValueChange={(valor) => cambiar(t.tipo, canal, valor)}
                    >
                      <SelectTrigger id={id} className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {FRECUENCIAS.map((f) => (
                          <SelectItem key={f.value} value={f.value}>
                            {f.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
