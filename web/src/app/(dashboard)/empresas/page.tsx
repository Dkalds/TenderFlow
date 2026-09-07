"use client";

import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { useAdmin } from "@/hooks/use-admin";
import { useDebounce } from "@/hooks/use-debounce";
import { useEmpresasWatchlist, useToggleEmpresaWatch } from "@/hooks/use-empresas-watchlist";
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { ApiError } from "@/lib/api-client";
import { formatNumber, formatPercent } from "@/lib/utils";
import { ContextLine } from "./_components/context-line";
import { EmpresaPerfil } from "./_components/empresa-perfil";
import { MaestroList } from "./_components/maestro-list";
import { ReviewQueue } from "./_components/review-queue";
import {
  useEmpresaDetail,
  useEmpresaPerfil,
  useEmpresasList,
  useEmpresasStats,
  type EmpresaSortKey,
} from "./_hooks/use-maestro";
import { UNDO_MS, useReviewQueue, type ConfidenceFilter } from "./_hooks/use-review-queue";

/**
 * Empresas — maestro canónico, ficha y cola de revisión.
 *
 * Dos vistas del mismo dato en `?vista=`: el maestro con su ficha al lado, y
 * la cola de matches dudosos. Tres decisiones gobiernan la pantalla:
 *
 * 1. **El orden y la paginación son del servidor.** Ordenar en cliente sobre
 *    la página traída reordena 12 filas de 1.284, que contesta a una pregunta
 *    distinta de la que hace quien pulsa «Importe».
 * 2. **Una sola alarma por fila.** En la cola, el NIF divergente; la similitud
 *    es una barra neutra. Dos códigos de color sobre la misma fila no dicen
 *    dos cosas, dicen ninguna.
 * 3. **El error es por bloque.** El maestro y la cola vienen de endpoints
 *    distintos: que caiga uno no puede tumbar el otro.
 */

/** Por debajo de este % de importe resuelto, las cuotas de Competencia mienten. */
const UMBRAL_RESUELTO = 95;

/** Las columnas de texto entran A→Z; las de cifra, de mayor a menor. */
const SENTIDO_INICIAL = (key: EmpresaSortKey): "asc" | "desc" => (key === "nombre" || key === "nif" ? "asc" : "desc");

export default function EmpresasPage() {
  const space = CONSOLE_SPACES.find((candidate) => candidate.key === "empresas")!;
  const { view, setView } = useSpaceView(space);
  const isAdmin = useAdmin();

  // Deep-link externo: `?q=` desde los grafos de Relaciones y desde el botón
  // «Maestro ↗» de Competencia. Se marca en el buscador mientras no se toque,
  // para que se vea de dónde sale el filtro con el que se ha aterrizado.
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(() => searchParams?.get("q") ?? "");
  const [fromDeepLink, setFromDeepLink] = useState(() => Boolean(searchParams?.get("q")));
  const debouncedSearch = useDebounce(search, 300);

  const [page, setPage] = useState(0);
  const { sortKey, sortDir, toggleSort } = useSortToggle<EmpresaSortKey>("importe", "desc", SENTIDO_INICIAL);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filtroConfianza, setFiltroConfianza] = useState<ConfidenceFilter>("all");

  const stats = useEmpresasStats();
  const lista = useEmpresasList({ search: debouncedSearch, page, sort: sortKey, order: sortDir });
  const { watchedIds } = useEmpresasWatchlist();
  const toggleWatch = useToggleEmpresaWatch();
  const onCommitError = useCallback(() => toast.error("No se pudo guardar la decisión · la fila vuelve a la cola"), []);
  const revisiones = useReviewQueue({
    enabled: view === "revision" && isAdmin,
    onCommitError,
  });

  const rows = useMemo(() => lista.data?.items ?? [], [lista.data]);

  // Primera fila seleccionada al cargar, derivando en vez de sincronizando con
  // un efecto: sin selección explícita, la ficha es la de la primera fila. Eso
  // ahorra el panel «ninguna empresa seleccionada», que ocupaba media pantalla
  // para no decir nada, y evita el render extra de un `setState` en efecto.
  const activeId = selectedId ?? rows[0]?.empresa_id ?? null;

  const detail = useEmpresaDetail(activeId);
  const perfil = useEmpresaPerfil(activeId);

  const onSort = useCallback(
    (key: EmpresaSortKey) => {
      toggleSort(key);
      setPage(0);
    },
    [toggleSort],
  );

  // Buscar es empezar de nuevo: vuelve a la primera página y suelta la
  // selección, para que la ficha sea la primera del resultado y no una fila
  // que ya no está en la lista. Paginar, en cambio, no la suelta: el usuario
  // eligió una ficha y pasar de página no es dejar de mirarla.
  const onSearchChange = useCallback((value: string) => {
    setSearch(value);
    setFromDeepLink(false);
    setPage(0);
    setSelectedId(null);
  }, []);

  const onToggleWatch = useCallback(
    (empresaId: number, watched: boolean) => {
      toggleWatch.mutate(
        { empresaIds: [empresaId], watched },
        {
          onSuccess: () =>
            toast.success(watched ? "Retirada de la vigilancia" : "Añadida a la vigilancia · alerta diaria"),
          onError: () => toast.error("No se pudo cambiar la vigilancia"),
        },
      );
    },
    [toggleWatch],
  );

  const { decidir, deshacer } = revisiones;
  const onDecidir = useCallback(
    (ids: number[], accept: boolean, descripcion: string) => {
      decidir(ids, accept);
      // La ventana del toast y la del envío son la misma: mientras se pueda
      // pulsar «Deshacer», la escritura todavía no ha salido.
      toast(descripcion, {
        duration: UNDO_MS,
        action: { label: "Deshacer", onClick: () => deshacer() },
      });
    },
    [decidir, deshacer],
  );

  const pendientes = stats.data?.revisiones_pendientes ?? 0;
  const pctImporte = stats.data?.pct_importe;
  const bajoUmbral = pctImporte != null && pctImporte < UMBRAL_RESUELTO;

  const contexto = [
    {
      key: "canonicas",
      label: "Canónicas",
      value: stats.data ? formatNumber(stats.data.empresas, "es-ES", { agruparSiempre: true }) : "…",
      title: "Empresas en el maestro",
    },
    {
      key: "resuelto",
      label: "Importe resuelto",
      value: pctImporte != null ? formatPercent(pctImporte) : "…",
      warn: bajoUmbral,
      title: stats.data
        ? `${formatNumber(stats.data.adjudicaciones_enlazadas, "es-ES", { agruparSiempre: true })} de ${formatNumber(stats.data.adjudicaciones_total, "es-ES", { agruparSiempre: true })} adjudicaciones enlazadas. Por debajo del ${UMBRAL_RESUELTO}% las cuotas de Competencia arrastran el error. Abre la cola de revisión`
        : "Cobertura de la resolución de entidades",
      onClick: () => setView("revision"),
    },
    {
      key: "vigiladas",
      label: "Vigiladas",
      value: formatNumber(watchedIds.size),
      title: "Empresas con alerta diaria",
    },
    {
      key: "revisiones",
      label: "Revisiones",
      value: stats.data ? formatNumber(pendientes) : "…",
      title: "Matches dudosos pendientes · abre la cola",
      onClick: () => setView("revision"),
    },
  ];

  return (
    <SpaceShell
      spaceKey="empresas"
      view={view}
      onViewChange={setView}
      viewBadges={{ revision: pendientes > 0 ? formatNumber(pendientes) : undefined }}
      actions={<ContextLine items={contexto} />}
      bleed
    >
      {view === "revision" ? (
        isAdmin ? (
          <ReviewQueue
            items={revisiones.items}
            loading={revisiones.isLoading}
            error={revisiones.isError}
            errorDetail={detalleDeError(revisiones.error, "/api/v1/empresas/reviews")}
            onRetry={() => void revisiones.refetch()}
            filtro={filtroConfianza}
            onFiltroChange={setFiltroConfianza}
            onDecidir={onDecidir}
          />
        ) : (
          // La cola reescribe el maestro para toda la organización, así que la
          // API la reserva a administradores. Se dice, en lugar de dejar que
          // el 403 se pinte como un fallo de carga.
          <div className="px-6 py-20 text-center">
            <p className="text-tf-body text-foreground mb-1.5 font-medium">Cola reservada a administradores</p>
            <p className="text-tf-meta text-muted-foreground mx-auto max-w-[46ch]">
              Resolver un match dudoso reescribe el maestro canónico y recalcula las cuotas de Competencia para todos.
              Hay {formatNumber(pendientes)} pendientes.
            </p>
          </div>
        )
      ) : (
        <div className="flex h-full min-h-0">
          <MaestroList
            search={search}
            onSearchChange={onSearchChange}
            fromDeepLink={fromDeepLink}
            rows={rows}
            total={lista.data?.total ?? 0}
            page={page}
            onPageChange={setPage}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            selectedId={activeId}
            onSelect={setSelectedId}
            watchedIds={watchedIds}
            onToggleWatch={onToggleWatch}
            watchPending={toggleWatch.isPending}
            loading={lista.isLoading}
            error={lista.isError}
            errorDetail={detalleDeError(lista.error, "/api/v1/empresas")}
            onRetry={() => void lista.refetch()}
          />
          <div className="bg-card/40 flex min-w-0 flex-1 flex-col">
            {activeId == null && !lista.isLoading ? (
              <div className="grid flex-1 place-items-center p-10">
                <p className="text-tf-body text-muted-foreground">Ninguna empresa coincide con la búsqueda</p>
              </div>
            ) : (
              <EmpresaPerfil
                detail={detail.data}
                perfil={perfil.data}
                loading={lista.isLoading || detail.isLoading}
                watched={activeId != null && watchedIds.has(activeId)}
                onToggleWatch={() => activeId != null && onToggleWatch(activeId, watchedIds.has(activeId))}
                watchPending={toggleWatch.isPending}
                onOpenGrupo={onSearchChange}
                onOpenEmpresa={setSelectedId}
              />
            )}
          </div>
        </div>
      )}
    </SpaceShell>
  );
}

/** Código y ruta del fallo, que es lo que sirve para reportarlo. */
function detalleDeError(error: unknown, ruta: string): string {
  return error instanceof ApiError ? `${error.status} · ${ruta}` : ruta;
}
