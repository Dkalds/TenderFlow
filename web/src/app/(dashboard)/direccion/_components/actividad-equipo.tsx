"use client";

/**
 * F4.5 — Actividad del equipo, en Dirección.
 *
 * `GET /pursuits/actividad` existía con cursor y filtro por persona, y ninguna
 * pantalla lo llamaba: la pestaña era un texto que mandaba al Resumen, y
 * «Qué cambió desde tu última visita» sólo enseña lo posterior a tu última
 * entrada, así que una semana sin movimiento se leía como un producto roto.
 *
 * Aquí el feed entero, del más reciente al más antiguo, paginado por el cursor
 * que devuelve el backend. La pantalla no cuenta ni agrega eventos (ADR-014):
 * pinta las filas que llegan y dice cuándo no hay más.
 */
import * as React from "react";
import Link from "next/link";
import { useInfiniteQuery } from "@tanstack/react-query";
import { History } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { pursuitKeys } from "@/lib/query-keys";
import { formatDateTime, formatRelativeTime } from "@/lib/utils";

type ItemActividad = Schemas["ItemActividad"];

const PAGINA = 50;
const TODOS = "todos";

/**
 * Tipos del ledger `pursuit_events`, como verbo. Un tipo que no esté aquí se
 * pinta tal cual en vez de descartarse: un evento nuevo en backend tiene que
 * verse, aunque sea con su nombre técnico, hasta que alguien le ponga uno.
 */
const VERBO: Record<string, string> = {
  "pursuit.created": "abrió la oportunidad",
  "pursuit.updated": "actualizó la oportunidad",
  checklist_evaluated: "evaluó el go/no-go de",
  kit_item_marcado: "marcó un documento del kit de",
};

export function verboDeEvento(evento: string): string {
  return VERBO[evento] ?? evento;
}

function FilaActividad({ item }: { item: ItemActividad }) {
  return (
    <li className="border-border/60 flex flex-col gap-0.5 border-b py-2.5 last:border-b-0">
      <p className="text-sm leading-snug">
        {/* `actor` es null cuando la cuenta se dio de baja: el ledger es
            inmutable y se dice quién fue sin inventar un nombre. */}
        <span className="font-medium">{item.actor ?? "Alguien del equipo"}</span>{" "}
        <span className="text-muted-foreground">{verboDeEvento(item.evento)}</span>{" "}
        <Link href={`/oportunidades/${item.pursuit_id}`} className="font-medium hover:underline">
          {item.titulo ?? item.licitacion_id}
        </Link>
      </p>
      {/* La fecha absoluta va visible y no en `title`: el tooltip nativo no
          existe para teclado ni táctil, y «hace 8 días» solo no sitúa el evento. */}
      <time dateTime={item.cuando} className="text-muted-foreground text-xs">
        {formatRelativeTime(item.cuando)} · {formatDateTime(item.cuando)}
      </time>
    </li>
  );
}

export function ActividadEquipo({ organizationId }: { organizationId: number | null }) {
  const [usuario, setUsuario] = React.useState<number | null>(null);
  const miembros = useOrganizationMembers(organizationId);

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
  });

  const items = feed.data?.pages.flatMap((pagina) => pagina.items ?? []) ?? [];
  const activos = (miembros.data ?? []).filter((miembro) => miembro.status === "active");

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-xs">
          Quién abrió, actualizó y evaluó cada oportunidad del equipo, de lo más reciente a lo más
          antiguo.
        </p>
        {activos.length > 1 && (
          <Select
            value={usuario != null ? String(usuario) : TODOS}
            onValueChange={(valor) => setUsuario(valor === TODOS ? null : Number(valor))}
          >
            <SelectTrigger className="h-8 w-56 text-xs" aria-label="Filtrar por persona">
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
        )}
      </div>

      {feed.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : feed.isError ? (
        <EmptyState
          icon={History}
          title="No se ha podido cargar la actividad"
          hint={feed.error instanceof Error ? feed.error.message : "Vuelve a intentarlo en unos segundos."}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={History}
          title="Sin actividad"
          hint={
            usuario != null
              ? "Esta persona todavía no ha movido ninguna oportunidad."
              : "Cuando alguien del equipo abra o actualice una oportunidad, aparecerá aquí."
          }
        />
      ) : (
        <>
          <ol aria-label="Actividad del equipo">
            {items.map((item) => (
              <FilaActividad key={item.id} item={item} />
            ))}
          </ol>
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
            <p className="text-muted-foreground text-xs">No hay actividad anterior.</p>
          )}
        </>
      )}
    </section>
  );
}
