"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SpaceShell } from "@/components/layout/space-shell";
import { apiGet } from "@/lib/api-client";

/**
 * F4.2 — Cuadro de mando de dirección.
 *
 * El Embudo son tres barras y cuatro cifras. Con eso un owner no puede
 * responder ninguna de las preguntas que se hace: dónde ganamos, dónde
 * perdemos, cuánto tarda el ciclo. Este espacio **absorbe** el embudo como
 * `?vista=embudo` —sin quitarlo de Mi Pipeline— y le añade los cortes que allí
 * no caben.
 *
 * La regla de esta pantalla: **ninguna celda se pinta por debajo del mínimo**.
 * El backend devuelve `valor: null` con su `n`, y aquí se enseña el hueco con
 * el motivo. Un win rate del 100 % sobre dos cierres, en la pantalla que mira
 * dirección, es peor que un hueco: el hueco se pregunta, el número se cree.
 */

type Celda = { clave: string; valor: number | null; n: number };
type Cuadro = {
  organization_id: number;
  win_rate_por_tecnologia: Celda[];
  win_rate_por_organo: Celda[];
  n_minimo: number;
};

function CorteTabla({
  titulo,
  filas,
  minimo,
}: {
  titulo: string;
  filas: Celda[];
  minimo: number;
}) {
  if (filas.length === 0) {
    return (
      <EmptyState
        title={`Sin cierres para ${titulo.toLowerCase()}`}
        hint="El win rate necesita oportunidades cerradas. Todavía no hay ninguna en este corte."
      />
    );
  }
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">{titulo}</h2>
      <p className="text-muted-foreground text-xs">
        Win rate sobre oportunidades cerradas. Se publica a partir de {minimo} cierres: por
        debajo, el porcentaje diría más de la casualidad que del equipo.
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{titulo}</TableHead>
            <TableHead className="w-24 text-right">Cierres</TableHead>
            <TableHead className="w-32 text-right">Win rate</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filas.map((fila) => (
            <TableRow key={fila.clave}>
              <TableCell className="font-medium">{fila.clave}</TableCell>
              <TableCell className="tf-tnum text-right">{fila.n}</TableCell>
              <TableCell className="tf-tnum text-right">
                {fila.valor === null ? (
                  <span className="text-muted-foreground text-xs">
                    aún no ({fila.n}/{minimo})
                  </span>
                ) : (
                  `${Math.round(fila.valor * 100)} %`
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

export default function DireccionPage() {
  const [vista, setVista] = React.useState("resultado");
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["direccion"],
    queryFn: () => apiGet("/api/v1/pursuits/direccion" as never) as Promise<Cuadro>,
    retry: false,
  });

  return (
    <SpaceShell spaceKey="direccion" view={vista} onViewChange={setVista}>
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <EmptyState
          icon={LayoutDashboard}
          title="Dirección es para owner y admin"
          hint={
            error instanceof Error
              ? error.message
              : "Tu rol en esta organización no permite ver este espacio."
          }
        />
      ) : vista === "actividad" ? (
        <EmptyState
          title="Actividad del equipo"
          hint="Quién abrió, decidió, presentó y cerró, en «Qué cambió desde tu última visita» del Resumen."
        />
      ) : (
        <div className="flex flex-col gap-8">
          <CorteTabla
            titulo="Tecnología"
            filas={data?.win_rate_por_tecnologia ?? []}
            minimo={data?.n_minimo ?? 5}
          />
          <CorteTabla
            titulo="Órgano"
            filas={data?.win_rate_por_organo ?? []}
            minimo={data?.n_minimo ?? 5}
          />
        </div>
      )}
    </SpaceShell>
  );
}
