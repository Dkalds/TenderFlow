"use client";

import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { useAdmin } from "@/hooks/use-admin";
import { useDebounce } from "@/hooks/use-debounce";
import { useEmpresasStats } from "@/hooks/use-empresas-stats";
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { PanelEmpty } from "@/components/console/panel";
import { formatNumber } from "@/lib/utils";
import { EmpresaPerfil } from "./empresa-perfil";
import { MaestroList } from "./maestro-list";
import { ReviewQueue } from "./review-queue";
import { useEmpresaDetail, useEmpresaPerfil, useEmpresasList, type EmpresaSortKey } from "../_hooks/use-maestro";
import { UNDO_MS, useReviewQueue, type ConfidenceFilter } from "../_hooks/use-review-queue";

/**
 * Competencia › Empresas y Competencia › Revisión — maestro canónico, identidad
 * y cola de coincidencias dudosas.
 *
 * Fueron el espacio Empresas hasta 2026-10. La pregunta es «quién es quién»;
 * cómo compite cada empresa lo cuentan las otras dos vistas y la ficha de
 * Competencia, a la que la de aquí enlaza. Ahora las cuatro son pestañas del
 * mismo espacio y no dos espacios que se enlazaban entre sí. `/empresas` y sus
 * `?vista=` redirigen aquí (`lib/space-views.ts`).
 *
 * El cuerpo es solo eso, el cuerpo: la cabecera —el contador de la cola en su
 * pestaña y la línea de contexto— la monta la página del espacio, que es quien
 * tiene el `SpaceShell`. Tres decisiones gobiernan la pantalla:
 *
 * 1. **El orden y la paginación son del servidor.** Ordenar en cliente sobre
 *    la página traída reordena 12 filas de 1.284, que contesta a una pregunta
 *    distinta de la que hace quien pulsa «Importe».
 * 2. **Una sola alarma por fila.** En la cola, el NIF divergente; la similitud
 *    es una barra neutra. Dos códigos de color sobre la misma fila no dicen
 *    dos cosas, dicen ninguna.
 * 3. **El error es por bloque.** El maestro y la cola vienen de consultas
 *    distintas: que caiga una no puede tumbar la otra. El error se dice en
 *    su bloque (`PanelError`, con el detalle técnico plegado) y sin toast.
 */

/** Las columnas de texto entran A→Z; las de cifra, de mayor a menor. */
const SENTIDO_INICIAL = (key: EmpresaSortKey): "asc" | "desc" => (key === "nombre" || key === "nif" ? "asc" : "desc");

export default function EmpresasVista({ vista }: { vista: string }) {
  const isAdmin = useAdmin();

  // Deep-link: `?q=` desde la ficha de un competidor sin identidad en el
  // maestro (`competidor-perfil.tsx`) y desde el NIF o el nombre de cada
  // identidad de su dossier («Ver en el maestro»). Se marca en el buscador
  // mientras no se toque, para que se vea de dónde sale el filtro con el que se
  // ha aterrizado.
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
  const onCommitError = useCallback(() => toast.error("No se pudo guardar la decisión · la fila vuelve a la cola"), []);
  const revisiones = useReviewQueue({
    enabled: vista === "revision" && isAdmin,
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

  // El aviso dice lo que implica vigilar: una alerta diaria. Sale al pulsar,
  // como el del Radar; si el servidor rechaza el cambio, el botón no cambia de
  // estado y el error lo avisa el manejador global de mutaciones.
  const avisarVigilancia = useCallback((ahoraVigila: boolean) => {
    toast(ahoraVigila ? "Añadida a la vigilancia · alerta diaria" : "Retirada de la vigilancia");
  }, []);

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

  if (vista === "revision") {
    return isAdmin ? (
      <ReviewQueue
        items={revisiones.items}
        loading={revisiones.isLoading}
        error={revisiones.error}
        onRetry={() => void revisiones.refetch()}
        filtro={filtroConfianza}
        onFiltroChange={setFiltroConfianza}
        onDecidir={onDecidir}
      />
    ) : (
      // La cola reescribe el maestro para toda la organización, así que la
      // API la reserva a administradores. Se dice, en lugar de dejar que el
      // 403 se pinte como un fallo de carga.
      <PanelEmpty
        className="py-20"
        title="Cola reservada a administradores"
        hint={`Resolver una coincidencia dudosa reescribe el maestro canónico y recalcula las cuotas de Competencia para todos. Hay ${formatNumber(stats.data?.revisiones_pendientes ?? 0)} pendientes.`}
      />
    );
  }

  return (
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
        onWatchToggled={avisarVigilancia}
        loading={lista.isLoading}
        error={lista.error}
        onRetry={() => void lista.refetch()}
      />
      <div className="bg-card flex min-w-0 flex-1 flex-col">
        {lista.isError ? null : activeId == null && !lista.isLoading ? (
          // Con la lista en error, el maestro ya lo dice a la izquierda: aquí
          // no se pinta un «ninguna coincide» que no es verdad.
          <div className="grid flex-1 place-items-center p-10">
            <PanelEmpty title="Ninguna empresa coincide con la búsqueda" hint="Prueba con otro nombre, un alias o el NIF." />
          </div>
        ) : (
          <EmpresaPerfil
            detail={detail.data}
            perfil={perfil.data}
            perfilCargando={perfil.isLoading}
            loading={lista.isLoading || detail.isLoading}
            error={detail.error}
            onRetry={() => void detail.refetch()}
            onWatchToggled={avisarVigilancia}
            onOpenGrupo={onSearchChange}
            onOpenEmpresa={setSelectedId}
          />
        )}
      </div>
    </div>
  );
}
