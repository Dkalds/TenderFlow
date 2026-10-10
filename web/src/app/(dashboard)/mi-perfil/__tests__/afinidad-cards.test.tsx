import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CpvsInteresCard, nombreDeCpv, sugerirCpvs } from "../_components/afinidad-cards";

/**
 * Un CPV son ocho dígitos que nadie se sabe. Lo que se fija es que la tarjeta
 * los nombre con el catálogo que manda la API —sin llevar una lista propia— y
 * que un código que el catálogo no conoce siga siendo válido.
 */

const CATALOGO = [
  { codigo: "48000000", nombre: "Software y sistemas información" },
  { codigo: "72000000", nombre: "Servicios TI: consultoría, desarrollo, internet" },
  { codigo: "72260000", nombre: "Servicios relacionados con software" },
  { codigo: "72267000", nombre: "Mantenimiento y reparación de software" },
];

describe("nombreDeCpv", () => {
  it("nombra el código exacto", () => {
    expect(nombreDeCpv("72260000", CATALOGO)).toBe("Servicios relacionados con software");
  });

  it("un código parcial o más fino toma el nombre del nivel que lo contiene", () => {
    expect(nombreDeCpv("7226", CATALOGO)).toBe("Servicios relacionados con software");
    expect(nombreDeCpv("72262000", CATALOGO)).toBe("Servicios relacionados con software");
    expect(nombreDeCpv("72999999", CATALOGO)).toBe("Servicios TI: consultoría, desarrollo, internet");
  });

  it("lo que el catálogo no conoce se queda sin nombre, no con uno inventado", () => {
    expect(nombreDeCpv("45000000", CATALOGO)).toBeNull();
    expect(nombreDeCpv("72000000", [])).toBeNull();
  });
});

describe("sugerirCpvs", () => {
  it("busca por el principio del código", () => {
    expect(sugerirCpvs("7226", CATALOGO, []).map((s) => s.codigo)).toEqual(["72260000", "72267000"]);
  });

  it("busca por el nombre sin importar tildes ni mayúsculas", () => {
    expect(sugerirCpvs("CONSULTORIA", CATALOGO, []).map((s) => s.codigo)).toEqual(["72000000"]);
  });

  it("no sugiere lo que ya está elegido ni nada con el campo vacío", () => {
    expect(sugerirCpvs("7226", CATALOGO, ["72260000"]).map((s) => s.codigo)).toEqual(["72267000"]);
    expect(sugerirCpvs("  ", CATALOGO, [])).toEqual([]);
  });
});

function renderCard(props: Partial<React.ComponentProps<typeof CpvsInteresCard>> = {}) {
  const base = {
    cpvs: [] as string[],
    cpvInput: "",
    onCpvInputChange: vi.fn(),
    onAdd: vi.fn(),
    onRemove: vi.fn(),
    catalogo: CATALOGO,
    ...props,
  };
  return { ...render(<CpvsInteresCard {...base} />), props: base };
}

describe("CpvsInteresCard", () => {
  it("al escribir parte del nombre ofrece el código, y pulsarlo lo añade", () => {
    const { props } = renderCard({ cpvInput: "mantenimiento" });

    fireEvent.click(screen.getByRole("button", { name: "Añadir 72267000, Mantenimiento y reparación de software" }));

    expect(props.onAdd).toHaveBeenCalledWith("72267000");
    // Un nombre no es un código: no se regaña mientras haya algo que elegir.
    expect(screen.queryByText(/Ningún CPV con nombre coincide/)).not.toBeInTheDocument();
  });

  it("los chips llevan el nombre junto al código", () => {
    const { props } = renderCard({ cpvs: ["72000000", "45000000"] });

    const conNombre = screen.getByRole("button", {
      name: "Quitar 72000000, Servicios TI: consultoría, desarrollo, internet",
    });
    expect(conNombre).toHaveTextContent("72000000");
    // El que el catálogo no conoce sigue ahí, solo con su código.
    fireEvent.click(screen.getByRole("button", { name: "Quitar 45000000" }));
    expect(props.onRemove).toHaveBeenCalledWith("45000000");
  });

  it("un código válido que no está en el catálogo se puede añadir igual", () => {
    const { props } = renderCard({ cpvInput: "45000000" });

    const anadir = screen.getByRole("button", { name: "Añadir" });
    expect(anadir).not.toBeDisabled();
    fireEvent.click(anadir);

    expect(props.onAdd).toHaveBeenCalledWith();
  });

  it("lo que ni es un código ni coincide con ningún nombre se explica", () => {
    renderCard({ cpvInput: "zzz" });

    expect(screen.getByText(/Ningún CPV con nombre coincide/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Añadir" })).toBeDisabled();
  });

  it("sin catálogo funciona como antes: códigos a secas", () => {
    renderCard({ catalogo: [], cpvs: ["72000000"], cpvInput: "7226" });

    expect(screen.getByRole("button", { name: "Quitar 72000000" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "CPV que coinciden" })).not.toBeInTheDocument();
  });
});
