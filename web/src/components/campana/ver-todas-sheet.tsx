"use client";

/**
 * «Ver todas»: la bandeja completa de la campana, paginada y con filtro.
 *
 * Un panel lateral y no una página: es la continuación del menú de la campana,
 * se abre desde cualquier pantalla sin perder lo que se estaba mirando, y la
 * consola ya tiene trece espacios en el raíl. Una ruta propia habría sido otro
 * destino de navegación para algo que se consulta de paso.
 *
 * El orden es cronológico y estable (`GET /notifications/alerts`): abrir un
 * aviso lo marca como leído sin moverlo de página, así que «Siguientes» no
 * salta ninguno.
 */

import * as React from "react";
import Link from "next/link";
import { PanelEmpty, PanelError, Segmented } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { OrganizacionActiva } from "@/hooks/use-organization";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  type Aviso,
  AVISOS_POR_PAGINA,
  destinoDeAviso,
  type EstadoLectura,
  useAvisos,
  useMarcarLeidos,
} from "./avisos";

const FILTROS: readonly { value: EstadoLectura; label: string }[] = [
  { value: "todas", label: "Todas" },
  { value: "sin_leer", label: "Sin leer" },
  { value: "leidas", label: "Leídas" },
];

const VACIO: Record<EstadoLectura, { title: string; hint: string }> = {
  todas: {
    title: "No tienes avisos en esta organización",
    hint: "Aquí llegan las alertas de tus reglas, las menciones, y las tareas y plazos de tus oportunidades.",
  },
  sin_leer: { title: "Lo tienes todo leído", hint: "Los avisos nuevos aparecerán aquí." },
  leidas: { title: "Aún no has leído ningún aviso", hint: "Un aviso pasa aquí en cuanto lo abres." },
};

export function VerTodasSheet({
  organizationId,
  open,
  onOpenChange,
  onSilenciarRegla,
}: {
  organizationId: OrganizacionActiva;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSilenciarRegla: (ruleId: number) => void;
}) {
  const [estado, setEstado] = React.useState<EstadoLectura>("todas");
  const [pagina, setPagina] = React.useState(0);
  const offset = pagina * AVISOS_POR_PAGINA;
  const consulta = useAvisos(organizationId, {
    estado,
    limit: AVISOS_POR_PAGINA,
    offset,
    enabled: open,
  });
  const marcar = useMarcarLeidos(organizationId);

  const datos = consulta.data;
  const total = datos?.total ?? 0;
  const sinLeer = datos?.sin_leer ?? 0;
  const desde = total === 0 ? 0 : offset + 1;
  const hasta = Math.min(offset + AVISOS_POR_PAGINA, total);

  const cambiarFiltro = (siguiente: EstadoLectura) => {
    setEstado(siguiente);
    setPagina(0);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-3 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Notificaciones</SheetTitle>
          <SheetDescription>Lo que te concierne en la organización activa.</SheetDescription>
        </SheetHeader>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <Segmented
            aria-label="Filtrar por lectura"
            value={estado}
            onChange={cambiarFiltro}
            options={FILTROS.map((f) => (f.value === "sin_leer" ? { ...f, count: sinLeer } : f))}
          />
          {sinLeer > 0 && (
            <Button type="button" size="sm" variant="outline" onClick={() => marcar.mutate("todos")}>
              Marcar todo como leído
            </Button>
          )}
        </div>

        {consulta.isPending ? (
          <Skeleton className="h-48 w-full rounded-md" />
        ) : consulta.isError ? (
          <PanelError
            variant="inline"
            title="No se pudieron cargar tus avisos"
            error={consulta.error}
            onRetry={() => void consulta.refetch()}
          />
        ) : datos && datos.items.length > 0 ? (
          <>
            <ul className="divide-y divide-border/60">
              {datos.items.map((aviso) => (
                <FilaAviso
                  key={aviso.id}
                  aviso={aviso}
                  onAbrir={() => {
                    if (!aviso.read) marcar.mutate({ ids: [aviso.id] });
                  }}
                  onNavegar={() => onOpenChange(false)}
                  onSilenciarRegla={onSilenciarRegla}
                />
              ))}
            </ul>
            <nav aria-label="Páginas de avisos" className="flex items-center justify-between gap-2 pt-1">
              <span className="tf-tnum text-tf-meta text-muted-foreground">
                {desde}–{hasta} de {total}
              </span>
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={pagina === 0}
                  onClick={() => setPagina((p) => Math.max(0, p - 1))}
                >
                  Anteriores
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={hasta >= total}
                  onClick={() => setPagina((p) => p + 1)}
                >
                  Siguientes
                </Button>
              </div>
            </nav>
          </>
        ) : (
          <PanelEmpty size="sm" title={VACIO[estado].title} hint={VACIO[estado].hint} />
        )}
      </SheetContent>
    </Sheet>
  );
}

function FilaAviso({
  aviso,
  onAbrir,
  onNavegar,
  onSilenciarRegla,
}: {
  aviso: Aviso;
  onAbrir: () => void;
  onNavegar: () => void;
  onSilenciarRegla: (ruleId: number) => void;
}) {
  const destino = destinoDeAviso(aviso);
  const titulo = aviso.title ?? aviso.type;
  return (
    <li className="space-y-1 py-2.5">
      <div className="flex items-start gap-2">
        <span
          aria-hidden="true"
          className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", aviso.read ? "bg-transparent" : "bg-primary")}
        />
        <div className="min-w-0 flex-1">
          {destino ? (
            <Link
              href={destino}
              className="text-tf-body font-medium text-foreground hover:text-primary"
              onClick={() => {
                onAbrir();
                onNavegar();
              }}
            >
              {titulo}
            </Link>
          ) : (
            <p className="text-tf-body font-medium text-foreground">{titulo}</p>
          )}
          {!aviso.read && <span className="sr-only">{" (sin leer)"}</span>}
          {aviso.body && <p className="line-clamp-2 text-tf-meta text-muted-foreground">{aviso.body}</p>}
          <p className="text-tf-micro text-muted-foreground">{formatRelativeTime(aviso.created_at)}</p>
        </div>
      </div>
      {((!destino && !aviso.read) || aviso.rule_id != null) && (
        <div className="flex flex-wrap gap-1.5 pl-3.5">
          {!destino && !aviso.read && (
            <Button type="button" size="sm" variant="ghost" onClick={onAbrir}>
              Marcar como leído
            </Button>
          )}
          {aviso.rule_id != null && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Silenciar esta regla: ${titulo}`}
              onClick={() => onSilenciarRegla(aviso.rule_id!)}
            >
              Silenciar esta regla
            </Button>
          )}
        </div>
      )}
    </li>
  );
}
