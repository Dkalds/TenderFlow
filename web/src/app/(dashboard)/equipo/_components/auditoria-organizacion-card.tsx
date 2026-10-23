"use client";

/**
 * Rastro de auditoría de la organización, en Equipo → Actividad (CU-31).
 *
 * La pestaña ya enseña la actividad de las oportunidades (quién movió qué);
 * esto es lo otro: quién entró al equipo, quién cambió un rol, la
 * configuración, los NIF, el perfil de capacidad o los pesos del go/no-go. Lo
 * sirve `GET /organizations/{id}/audit` desde 2026-09 y ninguna pantalla lo
 * pedía: un cliente B2B tenía que pedírselo al operador.
 *
 * - **Solo propietario y administrador**: el rastro nombra a otros miembros y
 *   la API responde 403 a los demás. La página no monta este panel para ellos.
 * - **El actor viaja como id** (ADR-030 §D) y se nombra con la lista de
 *   miembros; quien ya no está se queda como «Usuario #id», sin inventarle
 *   nombre.
 * - **El CSV lo genera la API** sobre el mismo rango, del más reciente al más
 *   antiguo y hasta `TOPE_CSV_AUDITORIA` eventos; si llega al tope, se dice
 *   para que se acote por fechas.
 */

import { Download } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { descargarBlob } from "@/lib/export";
import { getErrorMessage } from "@/lib/query-feedback";
import { formatDateTime, formatNumber } from "@/lib/utils";

import {
  descargarCsvAuditoria,
  TOPE_CSV_AUDITORIA,
  useAuditoriaOrganizacion,
  type EntradaAuditoria,
  type RangoAuditoria,
} from "../_hooks/use-auditoria-organizacion";
import { etiquetaEventoAuditoria, etiquetaResultado } from "../_lib/eventos-auditoria";

function useNombresDeMiembros(organizationId: number): Map<number, string> {
  const miembros = useOrganizationMembers(organizationId);
  return React.useMemo(
    () =>
      new Map(
        (miembros.data ?? []).map((miembro) => [
          miembro.user_id,
          miembro.display_name ?? miembro.email ?? `Usuario #${miembro.user_id}`,
        ]),
      ),
    [miembros.data],
  );
}

function nombreActor(entrada: EntradaAuditoria, nombres: Map<number, string>): string {
  if (entrada.actor_user_id == null) return "Sistema";
  return nombres.get(entrada.actor_user_id) ?? `Usuario #${entrada.actor_user_id}`;
}

export function AuditoriaOrganizacionCard({ organizationId }: { organizationId: number }) {
  const [desde, setDesde] = React.useState("");
  const [hasta, setHasta] = React.useState("");
  const [descargando, setDescargando] = React.useState(false);
  const rango: RangoAuditoria = { desde: desde || null, hasta: hasta || null };
  const alReves = Boolean(desde && hasta && hasta < desde);

  const rastro = useAuditoriaOrganizacion(organizationId, rango, !alReves);
  const nombres = useNombresDeMiembros(organizationId);
  const entradas = React.useMemo(
    () => rastro.data?.pages.flatMap((pagina) => pagina.items) ?? [],
    [rastro.data],
  );

  const descargar = async () => {
    setDescargando(true);
    try {
      const { blob, filas } = await descargarCsvAuditoria(organizationId, rango);
      descargarBlob(`auditoria-organizacion-${organizationId}.csv`, blob, "auditoria-organizacion");
      if (filas >= TOPE_CSV_AUDITORIA) {
        toast.warning(
          `El CSV lleva los ${formatNumber(TOPE_CSV_AUDITORIA)} eventos más recientes del rango. Acota las fechas para llevarte los anteriores.`,
        );
      } else {
        toast.success(`CSV descargado: ${formatNumber(filas)} eventos.`);
      }
    } catch (fallo) {
      toast.error(getErrorMessage(fallo, "accion"));
    } finally {
      setDescargando(false);
    }
  };

  const idDesde = `auditoria-desde-${organizationId}`;
  const idHasta = `auditoria-hasta-${organizationId}`;

  return (
    <Panel>
      <PanelTitle title="Rastro de auditoría" hint="cambios en el equipo y su configuración, del más reciente al más antiguo" />
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Field label="Desde" htmlFor={idDesde} className="w-40">
          <Input id={idDesde} type="date" value={desde} max={hasta || undefined} onChange={(e) => setDesde(e.target.value)} />
        </Field>
        <Field label="Hasta" htmlFor={idHasta} className="w-40" error={alReves ? "Es anterior a «Desde»." : undefined}>
          <Input id={idHasta} type="date" value={hasta} min={desde || undefined} onChange={(e) => setHasta(e.target.value)} />
        </Field>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void descargar()}
          disabled={descargando || alReves}
          className="ml-auto"
        >
          <Download aria-hidden="true" />
          {descargando ? "Preparando…" : "Descargar CSV"}
        </Button>
      </div>

      {alReves ? null : rastro.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : rastro.isError ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar el rastro de auditoría"
          error={rastro.error}
          onRetry={() => void rastro.refetch()}
        />
      ) : entradas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title={desde || hasta ? "Nada registrado en esas fechas" : "Todavía no hay nada registrado"}
          hint="Aquí aparecen las altas y bajas de miembros, los cambios de rol, de configuración y de pesos."
        />
      ) : (
        <>
          <Table>
            <caption className="sr-only">Rastro de auditoría de la organización</caption>
            <TableHeader>
              <TableRow>
                <TableHead className="whitespace-nowrap">Cuándo</TableHead>
                <TableHead>Qué</TableHead>
                <TableHead>Quién</TableHead>
                <TableHead>Detalle</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entradas.map((entrada) => {
                const resultado = etiquetaResultado(entrada.outcome);
                return (
                  <TableRow key={entrada.id}>
                    <TableCell className="tf-tnum whitespace-nowrap text-tf-meta">
                      <time dateTime={entrada.ts}>{formatDateTime(entrada.ts)}</time>
                    </TableCell>
                    <TableCell>
                      {etiquetaEventoAuditoria(entrada.event_type)}
                      {resultado && (
                        <Badge variant="outline" className="ml-1.5">
                          {resultado}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>{nombreActor(entrada, nombres)}</TableCell>
                    <TableCell className="max-w-72 truncate font-mono text-tf-micro text-muted-foreground" title={entrada.detail}>
                      {entrada.detail}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {rastro.hasNextPage ? (
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => void rastro.fetchNextPage()}
              disabled={rastro.isFetchingNextPage}
            >
              {rastro.isFetchingNextPage ? "Cargando…" : "Cargar más"}
            </Button>
          ) : (
            <p className="mt-3 text-tf-meta text-muted-foreground">No hay eventos anteriores en este rango.</p>
          )}
        </>
      )}
    </Panel>
  );
}
