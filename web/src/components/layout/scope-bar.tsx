"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { usePathname, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AmbitoIntro } from "@/components/layout/ambito-intro";
import { BarraConAmbito, BarraSinAmbito } from "@/components/layout/scope-barras";
import { chipsDelAmbito } from "@/components/layout/scope-chips";
import { ScrollEdge, useScrollEdgeState } from "@/components/layout/scroll-edge";
import { CampanaDiferida, ExportarDiferido } from "@/components/layout/menus-diferidos";
import { useAnnounceOnChange } from "@/components/live-region";
import { useValorDiferido } from "@/hooks/use-valor-diferido";
import { useDataFreshness } from "@/hooks/use-data-freshness";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import { useFilters, useFilterParams } from "@/lib/filters";
import { useScopeHistory } from "@/lib/scope-history";
import { useUiStore } from "@/lib/ui-store";
import {
  FILTROS_OPT_IN,
  pageGlobalFilterKeys,
  pageOptInFilterKeys,
  pageSingleValueFilterKeys,
  pathUsesGlobalFilters,
  type GlobalFilterKey,
} from "@/lib/navigation";
import { formatNumber } from "@/lib/utils";
import { analyticsKeys } from "@/lib/query-keys";
import { useMetaFilters } from "@/hooks/use-meta-filters";

/**
 * Barra de ámbito — 52px, el objeto de contexto persistente.
 *
 * Reemplaza a la `GlobalFilterBar` de ocho `<select>` sueltos. El ámbito pasa
 * a ser **un objeto**: chips con clave y valor, deshacer/rehacer siempre
 * visibles, y un editor único tras «+ Añadir» que conserva los seis controles
 * de la barra anterior (búsqueda, fechas con presets, CCAA, tecnología, estado
 * e importe con presets). Nada de lo que había desaparece: cambia de sitio.
 *
 * El contrato por página se respeta igual que antes (`lib/navigation.ts`): una
 * página que no consume filtros no ve chips inertes, y si hay filtros activos
 * se dice en vez de fingir que aplican. Eso vale también para el caso
 * intermedio —la página que aplica solo un subconjunto—: los chips, el recuento
 * y el aviso se calculan todos sobre ese mismo subconjunto, para que la barra
 * no pueda afirmar un número que la pantalla no está enseñando.
 *
 * Las piezas viven al lado: el editor en `scope-editor.tsx`, los chips en
 * `scope-chips.tsx` y las dos ramas de contenido en `scope-barras.tsx`.
 */

// El editor solo existe con «+ Añadir» abierto: llega al abrirlo, y se adelanta
// al acercarse al botón (`pedirCatalogo`). Mientras llega, el mismo rótulo de
// carga que la lista de vistas guardadas.
const cargarEditor = () => import("@/components/layout/scope-editor");
const ScopeEditor = dynamic(() => cargarEditor().then((modulo) => modulo.ScopeEditor), {
  ssr: false,
  loading: () => <p className="text-muted-foreground px-2 py-3 text-center text-tf-meta">Cargando…</p>,
});

/**
 * Params de URL que emite cada clave del ámbito (ver `filtersToParams` en
 * `lib/filters`).
 *
 * El contrato por página se expresa en CLAVES (`ccaa`, `estado`…) pero la query
 * viaja en PARAMS (`ccaa`, `solo_abiertas`…), y la correspondencia no es 1-a-1:
 * `fecha` produce dos params y `estado` otros dos. Sin este mapa no hay forma de
 * recortar los params al subconjunto que la pantalla aplica de verdad.
 */
const FILTER_KEY_PARAMS: Record<GlobalFilterKey, readonly string[]> = {
  q: ["q"],
  fecha: ["fecha_desde", "fecha_hasta"],
  ccaa: ["ccaa"],
  tecnologia: ["tecnologia"],
  estado: ["estado", "solo_abiertas"],
  importe: ["importe_min"],
  procedimiento: ["procedimiento"],
  provincia: ["provincia"],
  importe_max: ["importe_max"],
};

const TODAS_LAS_CLAVES = Object.keys(FILTER_KEY_PARAMS) as GlobalFilterKey[];

/**
 * Espera de la búsqueda antes de tocar la URL. Cada escritura cambia la clave
 * de todas las consultas con filtros —en Resumen, ~7 agregados sobre el
 * histórico entero— y apila una entrada de deshacer: por tecla eran siete
 * peticiones y una entrada por letra.
 */
const RETRASO_BUSQUEDA_MS = 300;

/**
 * Fondo sólido y no vidrio: el contenido se desplaza en `#main-content`, que es
 * hermano de la barra, y nunca pasa por debajo de ella. El corte con lo que se
 * desplaza lo dibuja el borde de scroll (`scroll-edge.tsx`).
 */
const CABECERA =
  "sticky top-0 z-30 flex h-[52px] flex-none [scrollbar-width:none] items-center gap-2.5 overflow-x-auto bg-background px-3.5 [&::-webkit-scrollbar]:hidden";

type Overview = ApiGetResult<"/api/v1/analytics/overview">;

export function ScopeBar() {
  const pathname = usePathname();
  const filters = useFilters();
  const filterParams = useFilterParams();
  const activeCount = Object.keys(filterParams).length;
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const { relative } = useDataFreshness();
  const { canUndo, canRedo, undo, redo } = useScopeHistory();
  const [editorOpen, setEditorOpen] = React.useState(false);
  // La búsqueda se teclea aquí y llega a la URL con retraso. Vive en la barra,
  // que no se desmonta al navegar, y no en el editor, que sí al cerrarse.
  const busqueda = useValorDiferido(filters.q, filters.setQ, RETRASO_BUSQUEDA_MS);
  // El separador con el contenido no es fijo: aparece sólo cuando hay algo
  // desplazado por debajo de la barra (ver `scroll-edge.tsx`).
  const scrolled = useScrollEdgeState();

  // El contrato de un espacio es el de la vista que se mira: Competencia ›
  // Empresas no lee el ámbito aunque Competidores sí (`lib/navigation.ts`). La
  // barra ya va dentro de un `Suspense` (`console-frame.tsx`).
  const searchParams = useSearchParams();
  const vista = searchParams?.get("vista") ?? null;
  // La ventana de cierre de /detalle no es un chip, pero acota la tabla: el
  // export la lleva para bajar lo que se ve.
  const cierreExport = React.useMemo(
    () => Object.fromEntries(["cierre_desde", "cierre_hasta"].flatMap((k) => (searchParams?.get(k) ? [[k, searchParams.get(k)!]] : []))),
    [searchParams],
  );
  const subsetKeys = pageGlobalFilterKeys(pathname, vista);
  const singleValueKeys = pageSingleValueFilterKeys(pathname);
  const optInKeys = React.useMemo(() => pageOptInFilterKeys(pathname, vista), [pathname, vista]);
  const filtersApply = pathUsesGlobalFilters(pathname, vista) || (subsetKeys?.length ?? 0) > 0;
  // Los filtros opt-in (F1.1) sólo se ven donde la página los declara; el
  // resto sigue el contrato de siempre (ausente = todos).
  const shows = React.useCallback(
    (key: GlobalFilterKey) =>
      FILTROS_OPT_IN.includes(key) ? optInKeys.includes(key) : !subsetKeys || subsetKeys.includes(key),
    [subsetKeys, optInKeys],
  );

  useAnnounceOnChange(
    filtersApply
      ? activeCount === 0
        ? "Sin filtros activos"
        : `${activeCount} ${activeCount === 1 ? "filtro activo" : "filtros activos"}`
      : null,
  );

  // `/meta/filters` (los catálogos de CCAA, tecnología, estado y
  // procedimiento) sólo lo usa el editor, que casi nunca se abre: se pedía en
  // cada carga de cada pantalla con ámbito. Ahora se pide al acercarse a
  // «+ Añadir» (puntero o foco, para que al abrir ya esté) o al abrirlo, y se
  // queda pedido. La única excepción es el primer render que ya lo necesita:
  // un chip de procedimiento se rotula con la etiqueta del catálogo, y sin él
  // enseñaría el código CODICE.
  const [catalogoPedido, setCatalogoPedido] = React.useState(false);
  const chipsSinEtiqueta = shows("procedimiento") && filters.procedimientos.length > 0;
  const { data: meta } = useMetaFilters(filtersApply && (catalogoPedido || chipsSinEtiqueta));
  const pedirCatalogo = React.useCallback(() => {
    setCatalogoPedido(true);
    void cargarEditor().catch(() => undefined);
  }, []);
  const onEditorOpenChange = React.useCallback((open: boolean) => {
    setEditorOpen(open);
    if (open) setCatalogoPedido(true);
  }, []);

  // Params con los que se pide el recuento: SOLO los del subconjunto que la
  // pantalla aplica de verdad.
  //
  // Antes se pedía con `useFilterParams()` completo. En una pantalla de
  // subconjunto —Radar aplica `tecnologia` y nada más— eso hacía que la barra
  // anunciara «312 licitaciones» calculadas con CCAA=Madrid mientras el Radar
  // enseñaba el top nacional. El aviso honesto que ya existía era inalcanzable
  // justo ahí, porque `filtersApply` es cierto en el caso subconjunto.
  const scopedParams = React.useMemo(() => {
    const allowed = new Set(TODAS_LAS_CLAVES.filter(shows).flatMap((key) => FILTER_KEY_PARAMS[key]));
    return Object.fromEntries(Object.entries(filterParams).filter(([param]) => allowed.has(param)));
  }, [filterParams, shows]);

  // Filtros activos que esta pantalla NO aplica. Cero cuando la página consume
  // el ámbito entero.
  const outOfScopeCount = activeCount - Object.keys(scopedParams).length;

  /** Limpia solo lo que no aplica: lo que sí filtra la pantalla se conserva. */
  const clearOutOfScope = React.useCallback(() => {
    const applies = shows;
    if (!applies("procedimiento")) filters.setProcedimientos([]);
    if (!applies("provincia")) filters.setProvincias([]);
    if (!applies("importe_max")) filters.setImporteMax(null);
    if (!applies("q")) filters.setQ("");
    if (!applies("fecha")) filters.setRango({ desde: null, hasta: null });
    if (!applies("estado")) {
      filters.setEstados([]);
      filters.setSoloAbiertas(false);
    }
    if (!applies("ccaa")) filters.setCcaas([]);
    if (!applies("tecnologia")) filters.setTecnologias([]);
    if (!applies("importe")) filters.setImporteMin(null);
  }, [filters, shows]);

  // Recuento del ámbito: el mismo dataset y la misma forma de clave que
  // `useFilteredQuery` (`[...baseKey, url, params]`), para que en las pantallas
  // que consumen el ámbito entero siga compartiendo caché con el resto de
  // consumidores de `/analytics/overview` en vez de duplicar la petición. No se
  // puede usar el hook directamente: siempre fusiona `useFilterParams()`
  // completo, que es justo lo que aquí hay que recortar.
  const { data: overview, isLoading: countLoading } = useQuery<Overview>({
    queryKey: analyticsKeys.overview(scopedParams),
    queryFn: ({ signal }) => {
      const search = new URLSearchParams(scopedParams).toString();
      return fetchWithAuth<Overview>(
        search ? `/api/v1/analytics/overview?${search}` : "/api/v1/analytics/overview",
        { signal },
      );
    },
    enabled: filtersApply,
    // Mismo comportamiento que `useFilteredQuery`: al cambiar el ámbito se
    // mantiene el número anterior en vez de parpadear a «—».
    placeholderData: keepPreviousData,
  });

  const chips = React.useMemo(() => chipsDelAmbito(filters, shows, meta), [filters, shows, meta]);

  // Contrato de filtros por página: donde no aplican, no se pintan chips que no
  // filtran nada. Si además hay filtros activos, se dice.
  //
  // Las dos ramas comparten cabecera y el hueco del final (exportar y campana),
  // en la misma posición del árbol; sólo cambia el contenido de la izquierda.
  // Antes cada rama pintaba su propia `NotificationBell`: al pasar de un
  // espacio con ámbito a otro sin él, React la desmontaba y la volvía a montar
  // (entonces cerraba y reabría un SSE; hoy perdería el menú abierto).
  return (
    <>
      {/* La barra scrollea en horizontal, así que el borde no puede vivir dentro
          (lo recortaría el `overflow`): va como hermano, con alto cero. */}
      <header data-slot="barra-ambito" className={CABECERA}>
        {filtersApply ? (
          <BarraConAmbito
            chips={chips}
            editor={
              <>
                <ScopeEditor
                  meta={meta}
                  shows={shows}
                  singleTecnologia={singleValueKeys.includes("tecnologia")}
                  busqueda={busqueda}
                />
                {activeCount > 0 && (
                  <div className="border-divider mt-1 border-t pt-2">
                    <Button variant="ghost" size="sm" className="w-full justify-start" onClick={filters.resetFilters}>
                      <RotateCcw aria-hidden="true" />
                      Limpiar el ámbito
                    </Button>
                  </div>
                )}
              </>
            }
            editorOpen={editorOpen}
            onEditorOpenChange={onEditorOpenChange}
            onAcercarseAlEditor={pedirCatalogo}
            historial={{ canUndo, canRedo, undo, redo }}
            outOfScopeCount={outOfScopeCount}
            onClearOutOfScope={clearOutOfScope}
            recuento={countLoading || !overview ? "—" : `${formatNumber(overview.total_licitaciones)} licitaciones`}
            relative={relative}
            onSearch={() => setCommandOpen(true)}
          />
        ) : (
          <BarraSinAmbito
            activeCount={activeCount}
            onReset={filters.resetFilters}
            relative={relative}
            onSearch={() => setCommandOpen(true)}
          />
        )}
        <div className="border-divider flex flex-none items-center gap-1 border-l pl-2.5">
          {/* «Exportar ámbito», no «Exportar» a secas: varias pantallas tienen su
              propia exportación con el corte de esa sección, y dos botones con la
              misma etiqueta a cuatro dedos de distancia no se distinguen. Este
              saca lo que gobierna esta barra — el ámbito activo. Sin ámbito, el
              rótulo de siempre. La talla es la de la consola (`sm`), la misma
              que «Buscar». */}
          <ExportarDiferido label={filtersApply ? "Exportar ámbito" : undefined} extraParams={cierreExport} />
          <CampanaDiferida />
        </div>
      </header>
      {/* Primer uso: qué es esta barra. Solo en la rama con ámbito, que es
          donde hay algo que explicar; se cierra una vez por navegador. */}
      {filtersApply && <AmbitoIntro />}
      {/* Detrás de la franja: el borde separa el cromo de lo que se desplaza
          en `#main-content`, y mientras la franja se ve el cromo acaba en ella. */}
      <ScrollEdge active={scrolled} />
    </>
  );
}
