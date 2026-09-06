"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SpaceShell } from "@/components/layout/space-shell";
import { apiGet, apiMutate } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";

/**
 * F1.5 — Cuentas objetivo.
 *
 * `Mercado → Órganos` es un corte analítico sin acción: enseña cuánto licita
 * un órgano y no deja hacer nada al respecto. Este espacio añade lo que
 * faltaba —seguirlo, y ver qué tiene el equipo con él— y **absorbe** aquella
 * vista como `?vista=mercado`, sin eliminarla: consolidar no quita
 * funcionalidad.
 *
 * Todo el estado es del servidor. El listado, el alta y la baja pasan por
 * `/cuentas`, que resuelve la organización y el permiso: un `viewer` recibe
 * 403 de la API, no un botón escondido.
 */

type Cuenta = {
  id: number;
  organo_nombre: string;
  organo_norm: string;
  nota?: string | null;
  created_at: string;
};

const CUENTAS_KEY = ["cuentas"] as const;

function useCuentas() {
  return useQuery({
    queryKey: CUENTAS_KEY,
    queryFn: () => apiGet("/api/v1/cuentas" as never) as Promise<Cuenta[]>,
  });
}

function SeguirOrgano() {
  const [organo, setOrgano] = React.useState("");
  const qc = useQueryClient();
  const seguir = useMutation({
    mutationFn: (nombre: string) =>
      apiMutate("POST", "/api/v1/cuentas", { organo: nombre }),
    onSuccess: () => {
      // Se mide la acción confirmada por el servidor, no la optimista: el
      // órgano no viaja —sería un identificador, y además revelaría a quién
      // persigue la organización.
      registrarEvento("organo_seguido", { accion: "seguir" });
      void qc.invalidateQueries({ queryKey: CUENTAS_KEY });
      setOrgano("");
      toast.success("Órgano añadido a tus cuentas");
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "No se pudo seguir el órgano"),
  });

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        const nombre = organo.trim();
        if (nombre) seguir.mutate(nombre);
      }}
    >
      <label className="min-w-64 flex-1 space-y-1.5 text-sm font-medium" htmlFor="nuevo-organo">
        Seguir un órgano
        <Input
          id="nuevo-organo"
          value={organo}
          onChange={(event) => setOrgano(event.target.value)}
          placeholder="Ayuntamiento de…"
          maxLength={500}
        />
      </label>
      <Button type="submit" disabled={!organo.trim() || seguir.isPending}>
        {seguir.isPending ? (
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        ) : (
          <Plus className="size-4" aria-hidden="true" />
        )}
        Seguir
      </Button>
    </form>
  );
}

function ListaCuentas() {
  const { data, isLoading, isError } = useCuentas();
  const qc = useQueryClient();
  const dejar = useMutation({
    mutationFn: (id: number) => apiMutate("DELETE", `/api/v1/cuentas/${id}` as never),
    onSuccess: () => {
      registrarEvento("organo_seguido", { accion: "dejar_de_seguir" });
      void qc.invalidateQueries({ queryKey: CUENTAS_KEY });
    },
    onError: () => toast.error("No se pudo dejar de seguir"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (isError) {
    return (
      <EmptyState
        title="No se pudieron cargar tus cuentas"
        hint="Vuelve a intentarlo en un momento."
      />
    );
  }

  const cuentas = data ?? [];
  if (cuentas.length === 0) {
    // Vacío declarado y con la acción al lado: una tabla en blanco se lee como
    // que la pantalla está rota, no como que todavía no hay nada.
    return (
      <EmptyState
        icon={Building2}
        title="Todavía no sigues ningún órgano"
        hint="Sigue los órganos con los que trabajas para ver sus publicaciones y sus vencimientos sin buscarlos."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Órgano</TableHead>
          <TableHead>Nota</TableHead>
          <TableHead className="w-24 text-right">Acciones</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {cuentas.map((cuenta) => (
          <TableRow key={cuenta.id}>
            <TableCell className="font-medium">{cuenta.organo_nombre}</TableCell>
            <TableCell className="text-muted-foreground">{cuenta.nota ?? "—"}</TableCell>
            <TableCell className="text-right">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => dejar.mutate(cuenta.id)}
                disabled={dejar.isPending}
              >
                <Trash2 className="size-4" aria-hidden="true" />
                <span className="sr-only">Dejar de seguir {cuenta.organo_nombre}</span>
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function CuentasPage() {
  const [vista, setVista] = React.useState("seguidas");

  return (
    <SpaceShell spaceKey="cuentas" view={vista} onViewChange={setVista}>
      {vista === "mercado" ? (
        <EmptyState
          icon={Building2}
          title="El análisis de órganos vive en Mercado"
          hint="Mercado → Órganos sigue siendo el corte analítico completo. Este espacio añade la acción: seguir un órgano y ver qué tiene tu equipo con él."
        />
      ) : (
        <div className="flex flex-col gap-6">
          <SeguirOrgano />
          <ListaCuentas />
        </div>
      )}
    </SpaceShell>
  );
}
