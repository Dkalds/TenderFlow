"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { ChevronDown } from "lucide-react";
import type { Chip } from "@/components/layout/scope-chips";
import { ICONO_CONCEPTO } from "@/lib/iconos";

// La hoja solo existe abierta: Radix Dialog llega al pulsar la fila, como el
// editor de escritorio llega al pulsar «+ Añadir».
const HojaAmbito = dynamic(() => import("@/components/layout/hoja-ambito").then((modulo) => modulo.HojaAmbito), {
  ssr: false,
});

const IconoFiltrar = ICONO_CONCEPTO.filtrar;

export interface BarraAmbitoMovilProps {
  chips: Chip[];
  /** «15 licitaciones», o «—» mientras llega. */
  recuento: string;
  outOfScopeCount: number;
  onClearOutOfScope: () => void;
  historial: { canUndo: boolean; canRedo: boolean; undo: () => void; redo: () => void };
  /** El mismo editor que el popover de escritorio (búsqueda, fechas, CCAA…). */
  editor: React.ReactNode;
  /** Se va a abrir: es el momento de pedir los catálogos del editor. */
  onAbrir: () => void;
  /** Lo que el export lleva además del ámbito (la ventana de cierre de /detalle). */
  extraExport: Record<string, string>;
}

/**
 * La barra de ámbito por debajo de `md`: una sola fila que dice qué filtra la
 * pantalla y cuántas licitaciones quedan, y que al pulsarla abre todo lo demás
 * en una hoja inferior (`hoja-ambito.tsx`).
 *
 * En escritorio la barra pone a la vista deshacer, rehacer, el rótulo, cada
 * chip, «+ Añadir», el recuento, la fecha, «Vistas» y «Exportar»; a 375 px eso
 * medía ~830 px y se desplazaba en horizontal, con «+ Añadir» a la vista pero
 * los chips y el export fuera. En el teléfono el patrón es el contrario:
 * resumen arriba, al alcance de un toque, y el editor en una hoja que sale de
 * abajo, donde llega el pulgar.
 */
export function BarraAmbitoMovil(props: BarraAmbitoMovilProps) {
  const { chips, recuento, outOfScopeCount, onAbrir } = props;
  const [abierta, setAbierta] = React.useState(false);
  // Se monta al abrirla por primera vez y se queda montada: así anima también
  // al cerrarse.
  const [montada, setMontada] = React.useState(false);

  const resumen = chips.length > 0 ? chips.map((chip) => `${chip.key} ${chip.value}`).join(" · ") : "Sin filtros";

  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={abierta}
        onClick={() => {
          onAbrir();
          setMontada(true);
          setAbierta(true);
        }}
        className="tf-pressable border-border bg-card text-tf-meta flex h-9 min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md border px-2.5 text-left md:hidden"
      >
        <IconoFiltrar className="text-muted-foreground h-4 w-4 flex-none" aria-hidden="true" />
        <span className="flex-none font-medium">Ámbito</span>
        {chips.length > 0 && (
          <span className="tf-tnum bg-primary-selected text-tf-micro text-primary flex-none rounded-sm px-1.5 font-semibold">
            {chips.length}
          </span>
        )}
        <span className="text-muted-foreground min-w-0 flex-1 truncate">
          {resumen}
          {outOfScopeCount > 0 && ` · ${outOfScopeCount} no ${outOfScopeCount === 1 ? "aplica" : "aplican"}`}
        </span>
        <span className="tf-tnum text-muted-foreground flex-none">{recuento}</span>
        <ChevronDown className="text-muted-foreground h-3.5 w-3.5 flex-none" aria-hidden="true" />
      </button>

      {montada && <HojaAmbito {...props} open={abierta} onOpenChange={setAbierta} />}
    </>
  );
}
