"use client";

import * as React from "react";
import { Info, Redo2, RotateCcw, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ScopeChip, type Chip } from "@/components/layout/scope-chips";
import { SavedViewsMenu } from "@/components/saved-views-menu";
import { cn } from "@/lib/utils";

/**
 * Las dos ramas de contenido de la barra de ámbito (`scope-bar.tsx`): la de
 * las pantallas que aplican el ámbito y la de las que no. Comparten la
 * cabecera y el hueco del final, que pinta la barra.
 */

const NAV_BUTTON = "grid h-6 w-6 place-items-center rounded-md border transition-colors";

/**
 * «Buscar» abre la paleta. El atajo se enseña en un `<kbd>` que el lector de
 * pantalla no lee (lo anuncia `aria-keyshortcuts`), así que el nombre
 * accesible es la palabra que se ve (WCAG 2.5.3); antes era «Abrir búsqueda y
 * comandos» sobre un botón que decía «Buscar ⌘K».
 */
// Acepta `ref` y el resto de props: va dentro de un `TooltipTrigger asChild`,
// que le pasa su ref y sus manejadores. En React 19 `ref` es una prop más.
function BotonBuscar({
  onSearch,
  onClick,
  className,
  ...props
}: React.ComponentProps<"button"> & { onSearch: () => void }) {
  return (
    <Button
      variant="outline"
      size="sm"
      {...props}
      onClick={(event) => {
        onClick?.(event);
        onSearch();
      }}
      aria-keyshortcuts="Control+K Meta+K"
      className={cn("text-muted-foreground hover:text-foreground flex-none", className)}
    >
      Buscar
      <kbd
        aria-hidden="true"
        className="border-divider text-tf-micro rounded-sm border px-1 py-0.5 font-mono leading-none font-normal"
      >
        ⌘K
      </kbd>
    </Button>
  );
}

/**
 * Cuándo se actualizaron los datos por última vez. En castellano y sin punto
 * de estado: el color no cambiaba con la antigüedad (salía verde también con
 * «sin registro»), y el pulso infinito se veía cien veces al día.
 */
function textoActualizacion(relative: string | null): string {
  return relative ? `Actualizado ${relative}` : "Sin actualizaciones registradas";
}

/**
 * Contenido de la barra en las pantallas que no aplican el ámbito. Comparte la
 * cabecera con scroll horizontal de la otra rama: sin él, a 375 px el rótulo
 * «Ámbito · no aplica…» más las utilidades medían ~650 px y empujaban el
 * documento entero (el desborde de 274 px de Mi Watchlist y de la Agenda en
 * `responsive.spec.ts`). El rótulo, además, se oculta en móvil.
 */
export function BarraSinAmbito({
  activeCount,
  onReset,
  relative,
  onSearch,
}: {
  activeCount: number;
  onReset: () => void;
  relative: string | null;
  onSearch: () => void;
}) {
  return (
    <>
      {activeCount > 0 ? (
        <>
          <Info className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {/* Por debajo de `md`, en una línea: encogido hasta su palabra más
              larga ocupaba nueve líneas (144 px) en una barra de 52 que las
              recortaba, y a 375 px solo se leía «no aplica en esta». Desde
              `md` la barra mide unos 700 px o más y el aviso, como mucho, se
              parte en dos líneas que caben: mejor eso que sacar Buscar y
              Exportar de la vista. */}
          <span className="text-tf-meta text-muted-foreground min-w-max md:min-w-auto">
            El ámbito global no aplica en esta pantalla ({activeCount}{" "}
            {activeCount === 1 ? "filtro activo" : "filtros activos"}).
          </span>
          <Button variant="ghost" size="sm" onClick={onReset}>
            <RotateCcw aria-hidden="true" />
            Limpiar
          </Button>
        </>
      ) : (
        <span className="text-tf-meta text-muted-foreground hidden flex-none sm:inline">
          El ámbito no aplica en esta pantalla.
        </span>
      )}
      <div className="flex-1" />
      <span className="text-tf-meta text-muted-foreground hidden flex-none sm:inline">
        {textoActualizacion(relative)}
      </span>
      <BotonBuscar onSearch={onSearch} />
    </>
  );
}

/** Contenido de la barra en las pantallas que aplican el ámbito (todo o parte). */
export function BarraConAmbito({
  chips,
  editor,
  editorOpen,
  onEditorOpenChange,
  onAcercarseAlEditor,
  historial,
  outOfScopeCount,
  onClearOutOfScope,
  recuento,
  relative,
  onSearch,
}: {
  chips: Chip[];
  editor: React.ReactNode;
  editorOpen: boolean;
  onEditorOpenChange: (open: boolean) => void;
  /** Puntero o foco sobre «+ Añadir»: el editor está a punto de abrirse. */
  onAcercarseAlEditor: () => void;
  historial: { canUndo: boolean; canRedo: boolean; undo: () => void; redo: () => void };
  outOfScopeCount: number;
  onClearOutOfScope: () => void;
  recuento: string;
  relative: string | null;
  onSearch: () => void;
}) {
  const { canUndo, canRedo, undo, redo } = historial;
  return (
    <>
      <div className="border-divider flex flex-none items-center gap-1.5 border-r pr-2.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={undo}
              disabled={!canUndo}
              aria-label="Deshacer cambio de ámbito"
              className={cn(
                NAV_BUTTON,
                canUndo
                  ? "border-border text-muted-foreground hover:text-foreground cursor-pointer"
                  : "border-divider-subtle text-muted-foreground/40 cursor-default",
              )}
            >
              <Undo2 className="h-3 w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Deshacer cambio de ámbito</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={redo}
              disabled={!canRedo}
              aria-label="Rehacer cambio de ámbito"
              className={cn(
                NAV_BUTTON,
                canRedo
                  ? "border-border text-muted-foreground hover:text-foreground cursor-pointer"
                  : "border-divider-subtle text-muted-foreground/40 cursor-default",
              )}
            >
              <Redo2 className="h-3 w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Rehacer cambio de ámbito</TooltipContent>
        </Tooltip>
      </div>

      <span className="text-tf-meta text-muted-foreground flex-none font-medium">Ámbito</span>

      {/* Nunca más estrecho que sus chips (`min-w-max`): si la barra no cabe
          —a 375 px siempre; en escritorio, con varios chips o con uno y el
          aviso de filtros que no aplican—, se desplaza ella. Con `min-w-0` era
          el único hijo que cedía ancho (sus hermanos son `flex-none`) y los
          chips se le salían por encima del aviso y del recuento: el `truncate`
          de cada chip solo corta valores de más de 160 px, no los estrecha. */}
      <div data-slot="ambito-chips" className="flex min-w-max items-center gap-1.5">
        {chips.map((chip) => (
          <ScopeChip key={`${chip.key}-${chip.value}`} chip={chip} />
        ))}

        <Popover open={editorOpen} onOpenChange={onEditorOpenChange}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-haspopup="dialog"
              onPointerEnter={onAcercarseAlEditor}
              onFocus={onAcercarseAlEditor}
              className="border-border text-tf-meta text-muted-foreground hover:border-primary-line-strong hover:text-foreground inline-flex h-6.5 flex-none cursor-pointer items-center gap-1.5 rounded-md border border-dashed bg-transparent px-2.5 font-medium transition-colors"
            >
              + Añadir
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80">
            {editor}
          </PopoverContent>
        </Popover>
      </div>

      {/* El caso subconjunto también merece el aviso. Antes solo se decía «el
            ámbito global no aplica» cuando NO aplicaba nada; con una pantalla
            que aplica parte del ámbito —Radar, que filtra por tecnología y por
            nada más— los filtros restantes quedaban activos, visibles en la URL
            y sin efecto, sin que nada lo dijera. Se ofrece quitarlos por
            separado: «Limpiar el ámbito» se llevaría por delante los que sí
            filtran esta pantalla. */}
      {outOfScopeCount > 0 && (
        <div className="flex flex-none items-center gap-1.5">
          <Info className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="text-tf-meta text-muted-foreground">
            {outOfScopeCount === 1
              ? "1 filtro activo no aplica en esta pantalla"
              : `${outOfScopeCount} filtros activos no aplican en esta pantalla`}
          </span>
          <Button variant="ghost" size="sm" onClick={onClearOutOfScope}>
            <RotateCcw aria-hidden="true" />
            {outOfScopeCount === 1 ? "Quitarlo" : "Quitarlos"}
          </Button>
        </div>
      )}

      <div className="flex-1" />

      <div className="text-tf-meta text-muted-foreground flex flex-none items-center gap-1.5">
        <span className="tf-tnum">{recuento}</span>
        <span aria-hidden="true">·</span>
        <span>{textoActualizacion(relative)}</span>
      </div>

      <SavedViewsMenu />

      <Tooltip>
        <TooltipTrigger asChild>
          <BotonBuscar onSearch={onSearch} />
        </TooltipTrigger>
        <TooltipContent>Licitaciones, órganos, empresas y acciones</TooltipContent>
      </Tooltip>
    </>
  );
}
