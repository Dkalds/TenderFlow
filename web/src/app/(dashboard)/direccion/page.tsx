"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";

import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { ApiError, apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { ICONO_ADMIN } from "@/lib/iconos";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";
import { ActividadEquipo } from "./_components/actividad-equipo";
import { PerdidasDireccion, RadarDireccion, TarjetasDireccion } from "./_components/cuadro-direccion";

/**
 * F4.2 — Cuadro de mando de dirección.
 *
 * El Embudo son tres barras y cuatro cifras. Con eso un propietario no puede
 * responder ninguna de las preguntas que se hace: dónde ganamos, dónde
 * perdemos, cuánto tarda el ciclo. Este espacio añade los cortes que en el
 * embudo no caben. Tuvo una vista `embudo` que era sólo un `EmptyState`
 * devolviendo a Mi Pipeline; la reestructura 2026-09-20 la retiró —no tenía
 * funcionalidad que conservar— y el embudo vive en Oportunidades →
 * Rendimiento.
 *
 * La regla de esta pantalla: **ninguna celda se pinta por debajo del mínimo**.
 * El backend devuelve `valor: null` con su `n`, y aquí se enseña el hueco con
 * el motivo. Una tasa de éxito del 100 % sobre dos cierres, en la pantalla que mira
 * dirección, es peor que un hueco: el hueco se pregunta, el número se cree.
 */

type Celda = Schemas["CorteMetrica"];

function CorteTabla({
  titulo,
  filas,
  minimo,
}: {
  titulo: string;
  filas: Celda[];
  minimo: number;
}) {
  const encabezado = `Tasa de éxito por ${titulo.toLowerCase()}`;
  if (filas.length === 0) {
    return (
      <Panel>
        <PanelTitle as="h2" title={encabezado} />
        <PanelEmpty
          size="sm"
          title={`Sin cierres para ${titulo.toLowerCase()}`}
          hint="La tasa de éxito necesita oportunidades cerradas, y todavía no hay ninguna en este corte."
        />
      </Panel>
    );
  }
  return (
    <Panel>
      <PanelTitle as="h2" title={encabezado} />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Sobre oportunidades cerradas. Se publica a partir de {minimo} cierres: con menos, el porcentaje diría
        más del azar que del equipo.
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{titulo}</TableHead>
            <TableHead className="w-24 text-right">Cierres</TableHead>
            <TableHead className="w-32 text-right">Tasa de éxito</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filas.map((fila) => (
            <TableRow key={fila.clave}>
              <TableCell className="font-medium">{fila.clave}</TableCell>
              <TableCell className="tf-tnum text-right">{fila.n}</TableCell>
              <TableCell className="tf-tnum text-right">
                {fila.valor == null ? (
                  <span className="text-muted-foreground text-tf-meta">
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
    </Panel>
  );
}

const SPACE = CONSOLE_SPACES.find((space) => space.key === "direccion")!;

export default function DireccionPage() {
  // La vista vive en `?vista=`, como en el resto de espacios: con estado
  // local, `/direccion?vista=embudo` aterrizaba en Resultado y la URL no
  // cambiaba al conmutar, así que el corte no era enlazable.
  const { view: vista, setView: setVista } = useSpaceView(SPACE);
  // Sin `organization_id` el backend resuelve la organización **personal**, y
  // las oportunidades viven en la del equipo: la pantalla salía vacía para
  // cualquier propietario mientras la Agenda, que sí la manda, las enseñaba.
  const organizationId = useActiveOrganizationId();
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: pursuitKeys.direccion(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/direccion", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    // Y por lo mismo tampoco se pregunta antes de saberlo: el `organization_id`
    // que falta en el primer render es exactamente el que vaciaba la pantalla.
    enabled: organizacionResuelta(organizationId),
    retry: false,
    // El fallo se pinta en la pantalla: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  return (
    <SpaceShell spaceKey="direccion" view={vista} onViewChange={setVista}>
      {isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : isError ? (
        // 403 es «tu rol no llega»; cualquier otro fallo es un fallo. Enseñarlo
        // todo como problema de permisos mandaba a un propietario a pelearse con
        // un rol correcto mientras la API estaba caída, y hacía invisible la caída.
        error instanceof ApiError && error.status === 403 ? (
          <Panel>
            <PanelEmpty
              icon={ICONO_ADMIN}
              title="Dirección es solo para propietarios y administradores"
              hint="Tu rol en esta organización no permite ver este espacio."
            />
          </Panel>
        ) : (
          <PanelError title="No se ha podido cargar Dirección" error={error} onRetry={() => void refetch()} />
        )
      ) : vista === "actividad" ? (
        <ActividadEquipo organizationId={organizationId} />
      ) : (
        <div className="flex flex-col gap-6">
          <TarjetasDireccion tarjetas={data?.tarjetas ?? []} />
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
          {data ? (
            <div className="grid gap-6 lg:grid-cols-2">
              <PerdidasDireccion cuadro={data} />
              <RadarDireccion cuadro={data} />
            </div>
          ) : null}
        </div>
      )}
    </SpaceShell>
  );
}
