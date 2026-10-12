/**
 * CU-30 — documentación acreditativa: tipo de documento y estado de vigencia.
 *
 * El estado lo calcula el servidor (`vigencias`); lo que se fija aquí es que
 * la pantalla lo pinta tal cual, en el orden que llega, y que el editor de
 * fila no ofrece un ámbito «equipo» para el papeleo de empresa.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { cambioDeTipo, filaDocumento } from "../organizacion-capacidad-documento";
import { OrganizacionVigencias, estadoDeVigencia } from "../organizacion-vigencias";

const VIGENCIAS = [
  {
    nombre: "Certificado Seguridad Social",
    tipo: "corriente_seguridad_social",
    categoria: "administrativa",
    vigente_hasta: "2026-10-09",
    estado: "caducado",
    dias_restantes: -3,
  },
  {
    nombre: "Certificado AEAT",
    tipo: "corriente_aeat",
    categoria: "administrativa",
    vigente_hasta: "2026-11-01",
    estado: "caduca_pronto",
    dias_restantes: 20,
  },
  {
    nombre: "ISO/IEC 27001",
    tipo: "certificacion_tecnica",
    categoria: "tecnica",
    vigente_hasta: "2027-11-16",
    estado: "vigente",
    dias_restantes: 400,
  },
  {
    nombre: "Inscripción ROLECE",
    tipo: "rolece",
    categoria: "administrativa",
    vigente_hasta: null,
    estado: "sin_caducidad",
    dias_restantes: null,
  },
] as const;

describe("OrganizacionVigencias", () => {
  it("pinta cada documento con su tipo y su estado, en el orden del servidor", () => {
    render(<OrganizacionVigencias vigencias={[...VIGENCIAS]} />);

    const seccion = screen.getByRole("region", { name: "Vigencia de la documentación" });
    const filas = within(seccion).getAllByRole("listitem");
    expect(filas).toHaveLength(4);
    ["Certificado Seguridad Social", "Certificado AEAT", "ISO/IEC 27001", "Inscripción ROLECE"].forEach(
      (nombre, i) => expect(within(filas[i]).getByText(nombre)).toBeInTheDocument(),
    );
    expect(within(filas[0]).getByText("Al corriente con la Seguridad Social")).toBeInTheDocument();
    expect(within(filas[0]).getByText(/^Caducado el /)).toBeInTheDocument();
    expect(within(filas[1]).getByText("Caduca en 20 días")).toBeInTheDocument();
    expect(within(filas[2]).getByText(/^Vigente hasta el /)).toBeInTheDocument();
    expect(within(filas[3]).getByText("Sin caducidad declarada")).toBeInTheDocument();
  });

  it("sin documentos declarados no pinta la sección", () => {
    const { container } = render(<OrganizacionVigencias vigencias={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("dice «hoy» y «mañana» en vez de cero y un días", () => {
    const base = { ...VIGENCIAS[1] };
    expect(estadoDeVigencia({ ...base, dias_restantes: 0 }).texto).toBe("Caduca hoy");
    expect(estadoDeVigencia({ ...base, dias_restantes: 1 }).texto).toBe("Caduca mañana");
    expect(estadoDeVigencia(VIGENCIAS[0]).tono).toBe("destructive");
  });
});

describe("filaDocumento", () => {
  const fila = { nombre: "", tipo: "certificacion_tecnica" as const, ambito: "team" as const, vigente_hasta: null };

  it("al elegir documentación administrativa la deja de empresa y sugiere el nombre", () => {
    expect(cambioDeTipo(fila, "corriente_aeat")).toEqual({
      tipo: "corriente_aeat",
      ambito: "company",
      nombre: "Al corriente con la AEAT",
    });
    // Lo que alguien ya escribió no se pisa.
    expect(cambioDeTipo({ ...fila, nombre: "AEAT 2026" }, "corriente_aeat")).toEqual({
      tipo: "corriente_aeat",
      ambito: "company",
    });
  });

  it("solo una certificación técnica pregunta el ámbito", () => {
    const { rerender } = render(<div>{filaDocumento(fila, vi.fn(), true)}</div>);
    expect(screen.getByText("Ámbito")).toBeInTheDocument();

    rerender(<div>{filaDocumento({ ...fila, tipo: "rolece", ambito: "company" }, vi.fn(), true)}</div>);
    expect(screen.queryByText("Ámbito")).not.toBeInTheDocument();
    expect(screen.getByText("Tipo")).toBeInTheDocument();
  });
});
