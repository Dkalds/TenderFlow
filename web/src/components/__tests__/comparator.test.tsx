import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Comparator } from "@/components/comparator";
import type { LicitacionDetail } from "@/components/detail-panel";

function makeItem(overrides: Partial<LicitacionDetail> = {}): LicitacionDetail {
  return {
    id_externo: "EXT-1",
    titulo: "Suministro de equipos",
    organo_contratacion: "Ayuntamiento",
    importe: 100000,
    estado: "Publicada",
    ccaa: "Madrid",
    cpv: "30200000",
    tecnologia: "Cloud",
    tipo_contrato: "Suministros",
    fecha_publicacion: "2024-01-01",
    fecha_limite: "2024-02-01",
    ...overrides,
  } as LicitacionDetail;
}

describe("Comparator", () => {
  it("shows an empty message when there are no items", () => {
    render(<Comparator items={[]} onClose={() => {}} />);
    expect(screen.getByText("No hay licitaciones para comparar.")).toBeInTheDocument();
  });

  it("renders a comparison row per field and a column per item", () => {
    render(
      <Comparator
        items={[makeItem(), makeItem({ id_externo: "EXT-2", importe: 250000 })]}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("Comparar licitaciones")).toBeInTheDocument();
    expect(screen.getByText("EXT-1")).toBeInTheDocument();
    expect(screen.getByText("EXT-2")).toBeInTheDocument();
    // Field labels appear.
    expect(screen.getByText("Importe")).toBeInTheDocument();
    expect(screen.getByText("Órgano de contratación")).toBeInTheDocument();
  });

  it("calls onClose from the close button and on Escape", () => {
    const onClose = vi.fn();
    render(<Comparator items={[makeItem()]} onClose={onClose} />);
    fireEvent.click(screen.getByText("Cerrar"));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
