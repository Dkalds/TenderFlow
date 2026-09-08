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
import { Bell } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
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
  const { data, isLoading, isError } = usePreferencias();
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
  if (isError) {
    return (
      <EmptyState
        title="No se pudieron cargar tus preferencias"
        hint="Volvé a intentarlo en un momento."
      />
    );
  }
  if (tipos.length === 0) {
    return (
      <EmptyState
        title="No hay avisos configurables"
        hint="El catálogo de avisos lo publica el backend; si está vacío, todavía no hay ninguno."
      />
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bell className="h-4 w-4" aria-hidden="true" />
          Qué avisos quieres recibir
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {tipos.map((t) => (
          <div key={t.tipo} className="border-border rounded-lg border p-3">
            <p className="text-sm font-medium">{t.label}</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {CANALES.map(({ canal, label }) => {
                const id = `${t.tipo}-${canal}`;
                return (
                  <div key={canal}>
                    <label htmlFor={id} className="text-muted-foreground mb-1 block text-xs">
                      {label}
                    </label>
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
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
