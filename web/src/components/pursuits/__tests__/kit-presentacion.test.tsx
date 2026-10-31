import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

/**
 * Un kit vacío dice por qué (sin ficha, extracción fallida o ficha sin
 * documentos) y, cuando se puede arreglar desde aquí, ofrece hacerlo.
 */
const h = vi.hoisted(() => ({
  kit: undefined as unknown,
  start: vi.fn(() => Promise.resolve()),
  running: false,
}));

vi.mock("@/hooks/use-pursuit-kit", () => ({
  usePursuitKit: () => ({ data: h.kit, isPending: false, error: null, refetch: vi.fn() }),
  useMarcarKitItem: () => ({ isPending: false, mutate: vi.fn() }),
  useAsignarKitItem: () => ({ isPending: false, mutate: vi.fn() }),
  registrarKitAbierto: vi.fn(),
  resumenKit: (kit?: { items?: Array<{ listo: boolean }> }) => ({
    listos: (kit?.items ?? []).filter((i) => i.listo).length,
    total: kit?.items?.length ?? 0,
  }),
}));
vi.mock("@/hooks/use-organization", () => ({ useOrganizationMembers: () => ({ data: [] }) }));
vi.mock("@/hooks/use-tender-fact-sheet", () => ({
  useTenderFactSheetExtraction: () => ({ start: h.start, isStarting: false, running: h.running }),
}));

import { KitPresentacionPanel } from "@/components/pursuits/kit-presentacion";

function vacio(estado_ficha: string) {
  return { licitacion_id: "LIC-1", items: [], sin_extraccion: true, estado_ficha };
}

afterEach(() => {
  h.start.mockClear();
  h.running = false;
});

describe("KitPresentacionPanel vacío", () => {
  it("sin ficha ofrece extraerla", () => {
    h.kit = vacio("sin_ficha");
    render(<KitPresentacionPanel pursuitId={17} organizationId={21} />);

    expect(screen.getByText("Aún no hay ficha del pliego")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Extraer ficha" }));
    expect(h.start).toHaveBeenCalledTimes(1);
  });

  it("con la extracción fallida ofrece reintentar", () => {
    h.kit = vacio("fallida");
    render(<KitPresentacionPanel pursuitId={17} organizationId={21} />);

    expect(screen.getByText("La última extracción de la ficha falló")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeEnabled();
  });

  it("mientras se extrae lo dice y no deja lanzar otra", () => {
    h.kit = vacio("sin_ficha");
    h.running = true;
    render(<KitPresentacionPanel pursuitId={17} organizationId={21} />);

    expect(screen.getByText("Extrayendo la ficha del pliego…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Extrayendo/ })).toBeDisabled();
  });

  it("con ficha y sin documentos no ofrece volver a extraer", () => {
    h.kit = vacio("extraida");
    render(<KitPresentacionPanel pursuitId={17} organizationId={21} />);

    expect(screen.getByText("La ficha del pliego no recoge documentos exigidos")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("KitPresentacionPanel con documentos", () => {
  it("enseña lo que dice el pliego de cada documento, con su condición", () => {
    h.kit = {
      licitacion_id: "LIC-1",
      sin_extraccion: false,
      estado_ficha: "extraida",
      items: [
        {
          clave: "0:garantia-provisional",
          nombre: "Garantía provisional",
          descripcion: "Garantía provisional, si el órgano de contratación la exige.",
          sobre: "otro",
          listo: false,
        },
      ],
    };
    render(<KitPresentacionPanel pursuitId={17} organizationId={21} />);

    expect(screen.getByText("Garantía provisional, si el órgano de contratación la exige.")).toBeInTheDocument();
  });
});
