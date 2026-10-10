import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BarraGuardado } from "../_components/barra-guardado";

/**
 * «Eliminar perfil» borraba al primer clic, pegado a «Guardar». Lo que se fija
 * es que ahora cueste dos, y que con cambios pendientes ni siquiera se ofrezca.
 */

function renderBarra(props: Partial<React.ComponentProps<typeof BarraGuardado>> = {}) {
  const base = {
    dirty: false,
    guardando: false,
    onGuardar: vi.fn(),
    onDescartar: vi.fn(),
    puedeEliminar: true,
    eliminando: false,
    onEliminar: vi.fn(),
    ...props,
  };
  return { ...render(<BarraGuardado {...base} />), props: base };
}

describe("BarraGuardado", () => {
  it("eliminar el perfil pide confirmación antes de borrar nada", () => {
    const { props } = renderBarra();

    fireEvent.click(screen.getByRole("button", { name: "Eliminar perfil" }));
    expect(props.onEliminar).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Confirmar eliminación del perfil" })).toHaveTextContent(
      /El Radar vuelve a los pesos globales/,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sí, eliminar" }));
    expect(props.onEliminar).toHaveBeenCalledTimes(1);
  });

  it("cancelar la confirmación no borra nada", () => {
    const { props } = renderBarra();

    fireEvent.click(screen.getByRole("button", { name: "Eliminar perfil" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(props.onEliminar).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Eliminar perfil" })).toBeInTheDocument();
  });

  it("sin perfil propio no hay nada que eliminar", () => {
    renderBarra({ puedeEliminar: false });

    expect(screen.queryByRole("button", { name: "Eliminar perfil" })).not.toBeInTheDocument();
  });

  it("sin cambios no se puede guardar ni hay nada que descartar", () => {
    renderBarra();

    expect(screen.getByRole("button", { name: "Guardar perfil" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Descartar" })).not.toBeInTheDocument();
    expect(screen.getByText("Sin cambios que guardar.")).toBeInTheDocument();
  });

  it("con cambios lo avisa, deja guardar o descartar y no ofrece eliminar", () => {
    const { props } = renderBarra({ dirty: true });

    expect(screen.getByRole("status")).toHaveTextContent("Cambios sin guardar");
    // Borrar ahora se llevaría también lo que aún no se ha guardado.
    expect(screen.queryByRole("button", { name: "Eliminar perfil" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(props.onDescartar).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Guardar perfil" }));
    expect(props.onGuardar).toHaveBeenCalledTimes(1);
  });

  it("si lo que hay en pantalla no se puede guardar, dice por qué en vez de ofrecerlo", () => {
    renderBarra({ dirty: true, motivoBloqueo: "Los pesos deben sumar 100 para guardar." });

    expect(screen.getByRole("status")).toHaveTextContent("Los pesos deben sumar 100 para guardar.");
    expect(screen.getByRole("button", { name: "Guardar perfil" })).toBeDisabled();
  });
});
