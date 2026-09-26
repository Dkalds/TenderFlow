/**
 * El buscador de órganos del alta: sólo se elige lo que existe.
 *
 * Sustituye al texto libre que guardaba «Ayuntamiento de Madrid» —un nombre que
 * ningún órgano tiene— y dejaba una cuenta que no avisaba de nada. Se fija que
 * se elige de la lista, con ratón y con teclado, y que un órgano de otra cuenta
 * no se puede elegir (el servidor lo rechazaría con 409).
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const busqueda = vi.hoisted(() => ({
  valor: {
    q: "",
    activa: false,
    pendiente: false,
    candidatos: [] as unknown[],
    isFetching: false,
    isError: false,
  },
}));

vi.mock("@/hooks/use-cuentas", () => ({ useBuscarOrganos: () => busqueda.valor }));

import { SelectorOrganos } from "@/app/(dashboard)/cuentas/_components/selector-organos";

const ECONOMIA = {
  organo_nombre: "Área de Gobierno de Economía del Ayuntamiento de Madrid",
  organo_norm: "area de gobierno de economia del ayuntamiento de madrid",
  expedientes: 11,
  cuenta_id: null,
  cuenta_nombre: null,
};
const INFORMATICA = {
  organo_nombre: "Organismo Autónomo Informática del Ayuntamiento de Madrid",
  organo_norm: "organismo autonomo informatica del ayuntamiento de madrid",
  expedientes: 73,
  cuenta_id: null,
  cuenta_nombre: null,
};
const DE_OTRA = {
  organo_nombre: "Junta de Gobierno del Ayuntamiento de Madrid",
  organo_norm: "junta de gobierno del ayuntamiento de madrid",
  expedientes: 5,
  cuenta_id: 9,
  cuenta_nombre: "Madrid (antigua)",
};

function conCandidatos(...candidatos: unknown[]) {
  busqueda.valor = {
    q: "madrid",
    activa: true,
    pendiente: false,
    candidatos,
    isFetching: false,
    isError: false,
  };
}

beforeEach(() => {
  busqueda.valor = {
    q: "",
    activa: false,
    pendiente: false,
    candidatos: [],
    isFetching: false,
    isError: false,
  };
});

afterEach(() => cleanup());

describe("SelectorOrganos", () => {
  it("con menos de tres letras pide más, y no enseña lista", () => {
    render(<SelectorOrganos seleccionados={[]} onChange={vi.fn()} />);

    expect(screen.getByText(/Escribe al menos 3 letras/)).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("elige y deja de elegir con el ratón", () => {
    conCandidatos(ECONOMIA, INFORMATICA);
    const onChange = vi.fn();
    const { rerender } = render(<SelectorOrganos seleccionados={[]} onChange={onChange} />);

    const opcion = screen.getByRole("option", { name: /Organismo Autónomo Informática/ });
    expect(opcion).toHaveTextContent("73 expedientes");
    fireEvent.mouseDown(opcion);
    expect(onChange).toHaveBeenLastCalledWith([INFORMATICA.organo_nombre]);

    rerender(<SelectorOrganos seleccionados={[INFORMATICA.organo_nombre]} onChange={onChange} />);
    const elegida = screen.getByRole("option", { name: /Organismo Autónomo Informática/ });
    expect(elegida).toHaveAttribute("aria-selected", "true");
    fireEvent.mouseDown(elegida);
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("con el teclado: las flechas mueven la activa y Enter la elige sin enviar el formulario", () => {
    conCandidatos(ECONOMIA, INFORMATICA);
    const onChange = vi.fn();
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <SelectorOrganos seleccionados={[]} onChange={onChange} />
      </form>,
    );

    const campo = screen.getByRole("combobox");
    fireEvent.keyDown(campo, { key: "ArrowDown" });
    const activa = campo.getAttribute("aria-activedescendant");
    expect(activa).toBeTruthy();
    expect(document.getElementById(activa ?? "")).toHaveTextContent(INFORMATICA.organo_nombre);

    fireEvent.keyDown(campo, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith([INFORMATICA.organo_nombre]);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("un órgano de otra cuenta dice de cuál y no se puede elegir", () => {
    conCandidatos(DE_OTRA);
    const onChange = vi.fn();
    render(<SelectorOrganos seleccionados={[]} onChange={onChange} />);

    const opcion = screen.getByRole("option", { name: /Junta de Gobierno/ });
    expect(opcion).toHaveAttribute("aria-disabled", "true");
    expect(opcion).toHaveTextContent("ya está en la cuenta «Madrid (antigua)»");
    fireEvent.mouseDown(opcion);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("al editar una cuenta, sus propios órganos salen marcados y bloqueados", () => {
    conCandidatos({ ...DE_OTRA, cuenta_id: 9 });
    const onChange = vi.fn();
    render(<SelectorOrganos seleccionados={[]} onChange={onChange} cuentaId={9} />);

    const opcion = screen.getByRole("option", { name: /Junta de Gobierno/ });
    expect(opcion).toHaveAttribute("aria-selected", "true");
    expect(opcion).toHaveTextContent("ya está en esta cuenta");
    fireEvent.mouseDown(opcion);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("dice cuando no hay coincidencias", () => {
    conCandidatos();

    render(<SelectorOrganos seleccionados={[]} onChange={vi.fn()} />);

    expect(screen.getByText("Ningún órgano contiene «madrid».")).toBeInTheDocument();
  });
});
