/**
 * La columna de datos y la decisión de la ficha: lo que se edita en su sitio.
 *
 * Se fija lo que la crítica de la ficha pedía: el importe de licitación en el
 * Resumen (y el del lote cuando la oportunidad es de un lote), la oferta y el
 * responsable editables en su celda, la próxima acción abierta desde fuera, y
 * una decisión del comité de una línea mientras no toca decidir.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Pursuit } from "@/hooks/use-pursuits";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const h = vi.hoisted(() => ({
  mutate: vi.fn(),
  licitacion: { data: undefined as unknown, isPending: false },
}));

vi.mock("@/hooks/use-pursuits", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-pursuits")>()),
  useUpdatePursuit: () => ({ mutate: h.mutate, isPending: false }),
}));
vi.mock("@/hooks/use-licitacion", () => ({ useLicitacion: () => h.licitacion }));
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationMembers: () => ({ data: [{ user_id: 5, display_name: "Ana Gómez", email: null }] }),
}));

import { DecisionComite } from "../_components/decision-comite";
import { FichaDatos, type CampoDeDatos } from "../_components/ficha-datos";
import { ProximaAccion } from "../_components/proxima-accion";

const base = {
  id: 12,
  organization_id: 7,
  licitacion_id: "0596/2026",
  tender_title: "Licencias SAP Analytics Cloud",
  tender_organo: "EMASESA",
  tender_deadline: null,
  status: "identified",
  decision: "pending",
  decision_reason: null,
  outcome: "pending",
  offer_price_eur: null,
  awarded_amount_eur: null,
  responsible_user_id: null,
  responsible_name: null,
  next_action: null,
  next_action_due: null,
  lote_id: null,
  lote_numero: null,
  expected_award: null,
  updated_at: "2026-09-23T10:00:00Z",
  version: 4,
} as unknown as Pursuit;

const en = (cambios: Partial<Pursuit>): Pursuit => ({ ...base, ...cambios }) as Pursuit;

/** La ficha controla qué celda está en edición; aquí, un estado local. */
function ConEdicion({ pursuit }: { pursuit: Pursuit }) {
  const [editando, setEditando] = React.useState<CampoDeDatos | null>(null);
  return <FichaDatos pursuit={pursuit} editando={editando} onEditar={setEditando} />;
}

beforeEach(() => {
  h.licitacion = { data: { importe: 188_131, lotes: [] }, isPending: false };
});

afterEach(() => h.mutate.mockClear());

describe("FichaDatos — el importe de lo que se licita", () => {
  it("enseña el importe de licitación en lugar de repetir el órgano", () => {
    render(<FichaDatos pursuit={base} />);
    expect(screen.getByText("Importe de licitación")).toBeInTheDocument();
    expect(screen.getByText(/188/)).toBeInTheDocument();
    // El órgano ya está en el subtítulo de la cabecera.
    expect(screen.queryByText("Órgano")).not.toBeInTheDocument();
  });

  it("de una oportunidad por lote, el importe es el del lote", () => {
    h.licitacion = {
      data: { importe: 188_131, lotes: [{ numero: "2", importe: 50_000 }] },
      isPending: false,
    };
    render(<FichaDatos pursuit={en({ lote_id: 3, lote_numero: "2" })} />);
    expect(screen.getByText("Importe del lote 2")).toBeInTheDocument();
    expect(screen.getByText(/50/)).toBeInTheDocument();
  });

  it("si el lote ya no se publica, dice que el importe es el del expediente", () => {
    render(<FichaDatos pursuit={en({ lote_id: null, lote_numero: "3" })} />);
    expect(screen.getByText("Importe del expediente")).toBeInTheDocument();
  });

  it("sin importe publicado lo dice, no pinta un cero", () => {
    h.licitacion = { data: { importe: null, lotes: [] }, isPending: false };
    render(<FichaDatos pursuit={base} />);
    expect(screen.getByText("Sin importe publicado")).toBeInTheDocument();
  });
});

describe("FichaDatos — oferta y responsable en su celda", () => {
  it("la oferta prevista se anota en su celda, con la misma regla que el formulario", () => {
    render(<ConEdicion pursuit={base} />);

    fireEvent.click(screen.getByRole("button", { name: "Anotar la oferta prevista" }));
    const campo = screen.getByLabelText("Oferta prevista, en euros");
    expect(campo).toHaveFocus();

    fireEvent.change(campo, { target: { value: "12k" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/Escribe un importe en euros/);
    expect(h.mutate).not.toHaveBeenCalled();

    fireEvent.change(campo, { target: { value: "170000" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(h.mutate).toHaveBeenCalledWith(
      { offer_price_eur: 170000, expected_version: 4 },
      expect.anything(),
    );
  });

  it("Escape cierra el editor sin guardar", () => {
    render(<ConEdicion pursuit={en({ offer_price_eur: 2_080_000 })} />);
    fireEvent.click(screen.getByRole("button", { name: "Editar la oferta prevista" }));
    fireEvent.keyDown(screen.getByLabelText("Oferta prevista, en euros"), { key: "Escape" });
    expect(screen.queryByLabelText("Oferta prevista, en euros")).not.toBeInTheDocument();
    expect(h.mutate).not.toHaveBeenCalled();
  });

  it("el responsable se asigna desde su celda", () => {
    render(<ConEdicion pursuit={base} />);
    fireEvent.click(screen.getByRole("button", { name: "Asignar un responsable" }));
    expect(screen.getByRole("combobox", { name: "Responsable de la oportunidad" })).toHaveFocus();
  });

  it("sin quien controle la edición, la rejilla es solo lectura", () => {
    render(<FichaDatos pursuit={base} />);
    expect(screen.queryByRole("button", { name: /oferta prevista/ })).not.toBeInTheDocument();
  });
});

describe("ProximaAccion — abierta desde fuera", () => {
  it("al abrirse lleva el foco al primer campo, y Escape la cierra", () => {
    const onEditar = vi.fn();
    const { rerender } = render(<ProximaAccion pursuit={base} editando={false} onEditar={onEditar} />);
    fireEvent.click(screen.getByRole("button", { name: "Añadir" }));
    expect(onEditar).toHaveBeenLastCalledWith(true);

    rerender(<ProximaAccion pursuit={base} editando onEditar={onEditar} />);
    const campo = screen.getByLabelText("Qué toca hacer");
    expect(campo).toHaveFocus();
    fireEvent.keyDown(campo, { key: "Escape" });
    expect(onEditar).toHaveBeenLastCalledWith(false);
  });
});

describe("DecisionComite", () => {
  it("antes de «Decisión» y sin decidir, es una línea", () => {
    render(<DecisionComite pursuit={base} />);
    expect(screen.getByText(/Se toma en la fase «Decisión»/)).toBeInTheDocument();
    expect(screen.queryByText("Sin decidir todavía.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "GO" })).not.toBeInTheDocument();
  });

  it("en «Decisión» se decide ahí mismo", () => {
    render(<DecisionComite pursuit={en({ status: "go_no_go" })} />);
    expect(screen.getByRole("button", { name: "GO" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NO-GO" })).toBeInTheDocument();
  });

  it("después, se lee con su motivo", () => {
    render(
      <DecisionComite pursuit={en({ status: "preparing", decision: "go", decision_reason: "Encaja con la práctica" })} />,
    );
    expect(screen.getByText("Encaja con la práctica")).toBeInTheDocument();
    expect(screen.getByText(/«Editar todos los campos»/)).toBeInTheDocument();
  });
});
