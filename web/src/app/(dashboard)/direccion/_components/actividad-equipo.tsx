"use client";

/**
 * F4.5 — Actividad del equipo, en Dirección y en Equipo → Actividad.
 *
 * Equipo lo monta para todos los roles: un miembro no entra en Dirección, y
 * el backend ya le quita los eventos de administración, así que el componente
 * no filtra nada por rol.
 *
 * El feed entero, del más reciente al más antiguo, paginado por el cursor que
 * devuelve el backend y agrupado por día. Cada línea dice qué cambió
 * (`cambios`: etapa, decisión, resultado, motivo), no sólo que algo cambió.
 * La pantalla no cuenta ni agrega eventos (ADR-014): coloca las filas que
 * llegan y dice cuándo no hay más.
 *
 * La persona filtrada vive en `?persona=`, como la vista en `?vista=`: «lo que
 * hizo Ana» es un enlace que se puede pegar. Se escribe sin navegar
 * (`reemplazarQuery`): ningún Server Component lee `persona`.
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useInfiniteQuery } from "@tanstack/react-query";

import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  organizacionResuelta,
  useOrganizationMembers,
  type OrganizacionActiva,
} from "@/hooks/use-organization";
import { agruparPorDia } from "@/lib/agrupar-por-dia";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";
import { queryActual, reemplazarQuery } from "@/lib/url-superficial";
import { formatHoraMinuto, formatRelativeTime } from "@/lib/utils";
import { etiquetaCambio, verboDeEvento } from "../_lib/actividad";

type ItemActividad = Schemas["ItemActividad"];

const PAGINA = 50;
const TODOS = "todos";

/** `?persona=7` → 7; cualquier otra cosa, sin filtro. */
function personaDeUrl(valor: string | null): number | null {
  const id = valor != null ? Number(valor) : Number.NaN;
  return Number.isInteger(id) && id > 0 ? id : null;
}

function FilaActividad({ item }: { item: ItemActividad }) {
  const cambios = item.cambios ?? [];
  return (
    <li className="border-border/60 flex flex-col gap-0.5 border-b py-2.5 last:border-b-0">
      <p className="text-tf-body leading-snug">
        {/* `actor` es null cuando la cuenta se dio de baja: el ledger es
            inmutable y se dice quién fue sin inventar un nombre. */}
        <span className="font-medium">{item.actor ?? "Alguien del equipo"}</span>{" "}
        <span className="text-muted-foreground">{verboDeEvento(item.evento, cambios)}</span>{" "}
        <Link href={`/oportunidades/${item.pursuit_id}`} className="font-medium hover:underline">
          {item.titulo ?? item.licitacion_id}
        </Link>
      </p>
      {cambios.length > 0 ? (
        <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-tf-meta" aria-label="Qué cambió">
          {cambios.map((cambio) => (
            <li key={cambio.campo}>{etiquetaCambio(cambio)}</li>
          ))}
        </ul>
      ) : null}
      {/* La hora va visible y no en `title`: el tooltip nativo no existe para
          teclado ni táctil. El día lo dice el encabezado del grupo. */}
      <time dateTime={item.cuando} className="text-muted-foreground text-tf-meta">
        {formatHoraMinuto(item.cuando)} · {formatRelativeTime(item.cuando)}
      </time>
    </li>
  );
}

function FiltroPersona({
  organizationId,
  usuario,
  onChange,
}: {
  organizationId: OrganizacionActiva;
  usuario: number | null;
  onChange: (usuario: number | null) => void;
}) {
  const miembros = useOrganizationMembers(organizationId);
  const activos = (miembros.data ?? []).filter((miembro) => miembro.status === "active");
  if (activos.length <= 1) return null;
  return (
    <Select
      value={usuario != null ? String(usuario) : TODOS}
      onValueChange={(valor) => onChange(valor === TODOS ? null : Number(valor))}
    >
      <SelectTrigger className="h-8 w-56 text-tf-meta" aria-label="Filtrar por persona">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={TODOS}>Todo el equipo</SelectItem>
        {activos.map((miembro) => (
          <SelectItem key={miembro.user_id} value={String(miembro.user_id)}>
            {miembro.display_name ?? miembro.email ?? `Usuario #${miembro.user_id}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function ActividadEquipo({ organizationId }: { organizationId: OrganizacionActiva }) {
  const params = useSearchParams();
  const usuario = personaDeUrl(params.get("persona"));
  const setUsuario = React.useCallback((siguiente: number | null) => {
    const search = queryActual();
    if (siguiente == null) search.delete("persona");
    else search.set("persona", String(siguiente));
    reemplazarQuery(search);
  }, []);

  const feed = useInfiniteQuery({
    queryKey: pursuitKeys.actividad(organizationId, usuario),
    queryFn: ({ pageParam }) =>
      apiGet("/api/v1/pursuits/actividad", {
        params: {
          query: {
            organization_id: organizationId ?? undefined,
            usuario: usuario ?? undefined,
            antes_de_id: pageParam ?? undefined,
            limit: PAGINA,
          },
        },
      }),
    initialPageParam: null as number | null,
    getNextPageParam: (pagina) => pagina.siguiente_cursor ?? undefined,
    // La actividad es la del equipo: sin saber de cuál, el feed sale con la de
    // la organización personal y se reemplaza a la vista del usuario.
    enabled: organizacionResuelta(organizationId),
    // El fallo se pinta en el feed (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const items = React.useMemo(
    () => feed.data?.pages.flatMap((pagina) => pagina.items ?? []) ?? [],
    [feed.data],
  );
  const dias = React.useMemo(() => agruparPorDia(items, new Date(), (item) => item.cuando), [items]);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-tf-meta">
          Quién abrió, movió, decidió y cerró cada oportunidad del equipo, de lo más reciente a lo más antiguo.
        </p>
        <FiltroPersona organizationId={organizationId} usuario={usuario} onChange={setUsuario} />
      </div>

      {feed.isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : feed.isError ? (
        <PanelError
          title="No se ha podido cargar la actividad"
          error={feed.error}
          onRetry={() => void feed.refetch()}
        />
      ) : items.length === 0 ? (
        <PanelEmpty
          title="Sin actividad"
          hint={
            usuario != null
              ? "Esta persona todavía no ha movido ninguna oportunidad."
              : "Cuando alguien del equipo abra o actualice una oportunidad, aparecerá aquí."
          }
        />
      ) : (
        <>
          <div className="flex flex-col gap-4">
            {dias.map((dia) => (
              <section key={dia.clave} aria-labelledby={`actividad-${dia.clave}`}>
                <h3 id={`actividad-${dia.clave}`} className="text-tf-micro font-semibold text-muted-foreground">
                  {dia.etiqueta}
                </h3>
                <ol aria-label={`Actividad del equipo, ${dia.etiqueta.toLowerCase()}`}>
                  {dia.eventos.map((item) => (
                    <FilaActividad key={item.id} item={item} />
                  ))}
                </ol>
              </section>
            ))}
          </div>
          {feed.hasNextPage ? (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => void feed.fetchNextPage()}
              disabled={feed.isFetchingNextPage}
            >
              {feed.isFetchingNextPage ? "Cargando…" : "Cargar más"}
            </Button>
          ) : (
            <p className="text-muted-foreground text-tf-meta">No hay actividad anterior.</p>
          )}
        </>
      )}
    </section>
  );
}
