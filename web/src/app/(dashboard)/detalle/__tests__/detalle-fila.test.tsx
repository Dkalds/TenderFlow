/**
 * Una fila de la tabla de Detalle desde 2026-10: ocho columnas, con órgano,
 * CCAA, procedimiento, expediente, CPV y publicación dentro de «Licitación».
 *
 * Se fija que ningún dato de las catorce columnas de antes se haya perdido por
 * el camino, que la fecha límite tenga columna propia con su plazo y que los
 * filtros cruzados filtren sin abrir la ficha.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { formatDate } from "@/lib/utils";
import type { MergedRow } from "../_hooks/detalle-table-model";

vi.mock("@/hooks/use-meta-filters", () => ({
  useMetaFilters: () => ({
    data: { procedimiento: [{ codigo: "1", etiqueta: "Abierto", descripcion: "Cualquier empresa puede presentar oferta." }] },
  }),
}));
vi.mock("@/components/seguir-boton", () => ({
  SeguirBoton: () => (
    <button type="button" aria-pressed={false}>
      Añadir a favoritos
    </button>
  ),
}));

import { COLUMNS } from "../_components/detalle-columnas";
import { DetalleFila } from "../_components/detalle-fila";

const DIA = 86_400_000;

const FILA = {
  id_externo: "placsp:41261680169928:CSE/9900/1101235435/26/PA",
  expediente: "CSE/9900/1101235435/26/PA",
  titulo: "Servicios de mantenimiento y soporte del Sistema de virtualización del puesto de trabajo",
  organo_contratacion: "Servicio Murciano de Salud - Gerencia",
  importe: 942_990,
  estado: "PUB",
  fecha_publicacion: "2026-10-27",
  // Relativa al reloj: `plazoVisual` cuenta los días desde ahora.
  fecha_limite: new Date(Date.now() + 24 * DIA).toISOString(),
  ccaa: "Murcia",
  cpv: "72590000",
  tecnologia: "CLOUD_INFRA",
  procedimiento: "1",
  score: 71.6,
  band: "Atractiva",
} as unknown as MergedRow;

function pintar(handlers: Partial<Record<"onOpen" | "onToggleCcaa" | "onToggleTecnologia", ReturnType<typeof vi.fn>>> = {}) {
  render(
    <TooltipProvider>
      <table>
        <tbody>
          <DetalleFila
            row={FILA}
            index={0}
            open={false}
            picked={false}
            isCursor={false}
            ccaaOn={false}
            tecOn={false}
            compact={false}
            rowHeight={64}
            atenuada={false}
            onOpen={handlers.onOpen ?? vi.fn()}
            onToggleSelect={vi.fn()}
            onToggleCcaa={handlers.onToggleCcaa ?? vi.fn()}
            onToggleTecnologia={handlers.onToggleTecnologia ?? vi.fn()}
          />
        </tbody>
      </table>
    </TooltipProvider>,
  );
  return screen.getByRole("row");
}

afterEach(cleanup);

describe("DetalleFila", () => {
  it("tiene una celda por columna", () => {
    const fila = pintar();
    expect(within(fila).getAllByRole("cell")).toHaveLength(COLUMNS.length);
  });

  it("reúne en «Licitación» los datos que antes tenían columna propia", () => {
    const fila = pintar();
    expect(within(fila).getByText(FILA.titulo)).toBeInTheDocument();
    expect(within(fila).getByText("Servicio Murciano de Salud - Gerencia")).toBeInTheDocument();
    expect(within(fila).getByRole("button", { name: "Filtrar por Murcia" })).toBeInTheDocument();
    expect(within(fila).getByText("CSE/9900/1101235435/26/PA")).toBeInTheDocument();
    expect(within(fila).getByText("CPV 72590000")).toBeInTheDocument();
    expect(within(fila).getByText(`pub. ${formatDate("2026-10-27")}`)).toBeInTheDocument();
    // El procedimiento, con su etiqueta legible del catálogo de `/meta/filters`.
    expect(within(fila).getByText("Abierto")).toBeInTheDocument();
  });

  it("da a la fecha límite columna propia, con los días que quedan", () => {
    const fila = pintar();
    expect(within(fila).getByText("24 d para cierre")).toBeInTheDocument();
  });

  it("los filtros cruzados filtran sin abrir la ficha", () => {
    const onOpen = vi.fn();
    const onToggleCcaa = vi.fn();
    const onToggleTecnologia = vi.fn();
    const fila = pintar({ onOpen, onToggleCcaa, onToggleTecnologia });
    fireEvent.click(within(fila).getByRole("button", { name: "Filtrar por Murcia" }));
    fireEvent.click(within(fila).getByRole("button", { name: "Filtrar por CLOUD_INFRA" }));
    expect(onToggleCcaa).toHaveBeenCalledWith("Murcia");
    expect(onToggleTecnologia).toHaveBeenCalledWith("CLOUD_INFRA");
    expect(onOpen).not.toHaveBeenCalled();

    fireEvent.click(fila);
    expect(onOpen).toHaveBeenCalledWith(0, FILA.id_externo);
  });
});
