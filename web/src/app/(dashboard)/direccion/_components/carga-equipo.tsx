"use client";

/**
 * Carga del equipo: quién tiene qué abierto hoy y qué de eso pide atención.
 *
 * Es la pregunta que el cuadro de resultados no responde —«¿el equipo está
 * trabajando lo que dijimos?»— y por eso es una vista y no una tarjeta más.
 * Cada recuento viene de `GET /pursuits/direccion/carga` (ADR-014); aquí sólo
 * se dibuja la barra de abiertas proporcional a la persona más cargada.
 *
 * Una fila por miembro activo, también los que no tienen nada: que alguien
 * esté libre es parte de la respuesta.
 */
import { useQuery } from "@tanstack/react-query";

import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { organizacionResuelta, type OrganizacionActiva } from "@/hooks/use-organization";
import { ApiError, apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";
import { cn, formatNumber } from "@/lib/utils";
import { SinPermisoDireccion } from "./sin-permiso";

type Responsable = Schemas["CargaResponsable"];

function Aviso({ n, tono }: { n: number; tono: "warning" | "destructive" }) {
  return (
    <span
      className={cn(
        "tf-tnum",
        n === 0 ? "text-muted-foreground" : tono === "warning" ? "font-semibold text-warning" : "font-semibold text-destructive",
      )}
    >
      {formatNumber(n)}
    </span>
  );
}

function FilaCarga({ persona, maximo }: { persona: Responsable; maximo: number }) {
  const abiertas = persona.abiertas ?? 0;
  return (
    <TableRow>
      <TableCell className="font-medium">
        {persona.user_id == null ? (
          <span className="text-muted-foreground">Sin responsable</span>
        ) : (
          (persona.nombre ?? `Usuario #${persona.user_id}`)
        )}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <svg className="h-3 w-24 flex-none" viewBox="0 0 100 1" preserveAspectRatio="none" aria-hidden="true">
            <rect className="fill-secondary/60" width="100" height="1" />
            <rect className="fill-primary/60" height="1" width={(abiertas / maximo) * 100} />
          </svg>
          <span className="tf-tnum font-semibold">{formatNumber(abiertas)}</span>
        </div>
      </TableCell>
      <TableCell className="tf-tnum text-right">{formatNumber(persona.presentadas ?? 0)}</TableCell>
      <TableCell className="text-right">
        <Aviso n={persona.plazos_proximos ?? 0} tono="warning" />
      </TableCell>
      <TableCell className="text-right">
        <Aviso n={persona.plazos_vencidos ?? 0} tono="destructive" />
      </TableCell>
      <TableCell className="text-right">
        <Aviso n={persona.sin_proxima_accion ?? 0} tono="warning" />
      </TableCell>
      <TableCell className="text-right">
        <Aviso n={persona.acciones_vencidas ?? 0} tono="destructive" />
      </TableCell>
    </TableRow>
  );
}

export function CargaEquipoView({ organizationId }: { organizationId: OrganizacionActiva }) {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: pursuitKeys.direccionCarga(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/direccion/carga", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    retry: false,
    meta: META_ERROR_EN_LINEA,
  });

  if (isError) {
    return error instanceof ApiError && error.status === 403 ? (
      <SinPermisoDireccion />
    ) : (
      <PanelError title="No se ha podido cargar la carga del equipo" error={error} onRetry={() => void refetch()} />
    );
  }
  if (isPending) return <Skeleton className="h-80 w-full rounded-xl" />;

  const responsables = data.responsables ?? [];
  const maximo = Math.max(1, ...responsables.map((persona) => persona.abiertas ?? 0));
  const horizonte = data.horizonte_dias;

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Carga del equipo"
        hint={`${formatNumber(data.total_abiertas ?? 0)} oportunidades abiertas hoy`}
      />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Los avisos cuentan sólo lo que está sin presentar: una oferta presentada espera un resultado, no
        trabajo de oferta.
      </p>
      {data.truncado ? (
        <p role="status" className="mb-3 text-tf-meta text-warning">
          Hay más oportunidades abiertas de las que caben en esta vista: las cifras son un mínimo.
        </p>
      ) : null}
      {responsables.length === 0 ? (
        <PanelEmpty size="sm" title="Nadie en el equipo todavía" hint="Invita a alguien desde Equipo." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Persona</TableHead>
              <TableHead>Abiertas</TableHead>
              <TableHead className="text-right">Presentadas</TableHead>
              <TableHead className="text-right">Plazo en {horizonte} días</TableHead>
              <TableHead className="text-right">Plazo vencido</TableHead>
              <TableHead className="text-right">Sin próxima acción</TableHead>
              <TableHead className="text-right">Acción vencida</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {responsables.map((persona) => (
              <FilaCarga key={persona.user_id ?? "sin-responsable"} persona={persona} maximo={maximo} />
            ))}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
