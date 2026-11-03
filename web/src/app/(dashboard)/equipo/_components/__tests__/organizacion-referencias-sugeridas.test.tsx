import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

/**
 * CU-30 — las referencias que la API propone desde las adjudicaciones a los NIF de la
 * organización. Se fija que se pueden añadir al borrador una a una o todas, y
 * que lo ya añadido deja de proponerse sin esperar al guardado.
 */

import { OrganizacionReferenciasSugeridas } from "../organizacion-referencias-sugeridas";

const SUGERIDAS = [
  { organo: "Diputación de Lugo", anio: 2025, importe_eur: 480000, tecnologia: "SAP", expediente_id: "EXP-1" },
  { organo: "Concello de Vigo", anio: 2024, importe_eur: null, tecnologia: null, expediente_id: "EXP-2" },
];

describe("OrganizacionReferenciasSugeridas", () => {
  it("añade una referencia propuesta al borrador", () => {
    const onAnadir = vi.fn();
    render(<OrganizacionReferenciasSugeridas sugeridas={SUGERIDAS} declaradas={[]} editable onAnadir={onAnadir} />);

    expect(screen.getByText("2 contratos ganados en los últimos tres años")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Añadir Diputación de Lugo (2025) a las referencias" }));

    expect(onAnadir).toHaveBeenCalledWith([SUGERIDAS[0]]);
  });

  it("añade todas de una vez", () => {
    const onAnadir = vi.fn();
    render(<OrganizacionReferenciasSugeridas sugeridas={SUGERIDAS} declaradas={[]} editable onAnadir={onAnadir} />);

    fireEvent.click(screen.getByRole("button", { name: "Añadir todos" }));

    expect(onAnadir).toHaveBeenCalledWith(SUGERIDAS);
  });

  it("deja de proponer lo que ya está en el borrador", () => {
    render(
      <OrganizacionReferenciasSugeridas
        sugeridas={SUGERIDAS}
        declaradas={[SUGERIDAS[0]]}
        editable
        onAnadir={vi.fn()}
      />,
    );

    expect(screen.getByText("Un contrato ganado en los últimos tres años")).toBeInTheDocument();
    expect(screen.queryByText("Diputación de Lugo")).not.toBeInTheDocument();
  });

  it("quien solo lee las ve sin botones", () => {
    render(
      <OrganizacionReferenciasSugeridas sugeridas={SUGERIDAS} declaradas={[]} editable={false} onAnadir={vi.fn()} />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("sin propuestas no pinta nada", () => {
    const { container } = render(
      <OrganizacionReferenciasSugeridas sugeridas={[]} declaradas={[]} editable onAnadir={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
