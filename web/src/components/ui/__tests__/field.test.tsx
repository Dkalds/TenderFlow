/**
 * `Field`: etiqueta, control, pista y error con una sola jerarquía, y el
 * contrato S7.2 (`lib/forms/campo.tsx`) para el lector de pantalla.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Field, ariaDeField, idAyuda, ETIQUETA_CAMPO } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { idError } from "@/lib/forms/campo";

describe("Field", () => {
  it("la etiqueta nombra el control", () => {
    render(
      <Field label="Importe mínimo" htmlFor="importe">
        <Input id="importe" />
      </Field>,
    );
    expect(screen.getByLabelText("Importe mínimo")).toHaveAttribute("id", "importe");
  });

  it("la etiqueta va a 12 px: por debajo del título del panel", () => {
    render(
      <Field label="Palabra clave" htmlFor="kw">
        <Input id="kw" />
      </Field>,
    );
    const etiqueta = screen.getByText("Palabra clave");
    expect(etiqueta.className).toBe(ETIQUETA_CAMPO);
    expect(etiqueta).toHaveClass("text-tf-meta");
    expect(etiqueta.className).not.toMatch(/text-sm/);
  });

  it("sin pista ni error no añade nada al control", () => {
    render(
      <Field label="Nombre" htmlFor="nombre">
        <Input id="nombre" />
      </Field>,
    );
    const control = screen.getByLabelText("Nombre");
    expect(control).not.toHaveAttribute("aria-describedby");
    expect(control).not.toHaveAttribute("aria-invalid");
  });

  it("la pista describe el control", () => {
    render(
      <Field label="CPV" htmlFor="cpv" hint="Ocho cifras, sin guion.">
        <Input id="cpv" />
      </Field>,
    );
    const control = screen.getByLabelText("CPV");
    expect(control).toHaveAttribute("aria-describedby", idAyuda("cpv"));
    expect(control).toHaveAccessibleDescription("Ocho cifras, sin guion.");
  });

  it("con error, el control se marca inválido y el error va antes que la pista", () => {
    render(
      <Field label="CPV" htmlFor="cpv" hint="Ocho cifras." error="El CPV tiene ocho cifras.">
        <Input id="cpv" />
      </Field>,
    );
    const control = screen.getByLabelText("CPV");
    expect(control).toHaveAttribute("aria-invalid", "true");
    expect(control).toHaveAttribute("aria-describedby", `${idError("cpv")} ${idAyuda("cpv")}`);
    expect(screen.getByText("El CPV tiene ocho cifras.")).toHaveAttribute("id", idError("cpv"));
    // Sin región viva por campo (S7.2): el error se lee al llegar al campo.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("conserva las descripciones que ya traía el control", () => {
    render(
      <Field label="Nota" htmlFor="nota" hint="Opcional.">
        <Input id="nota" aria-describedby="nota-general" />
      </Field>,
    );
    expect(screen.getByLabelText("Nota")).toHaveAttribute("aria-describedby", `${idAyuda("nota")} nota-general`);
  });
});

describe("ariaDeField", () => {
  it("da los atributos para un control anidado (el trigger de un Select)", () => {
    expect(ariaDeField("region", { hint: true, error: "Elige una." })).toEqual({
      "aria-invalid": true,
      "aria-describedby": `${idError("region")} ${idAyuda("region")}`,
    });
    expect(ariaDeField("region", {})).toEqual({ "aria-invalid": undefined, "aria-describedby": undefined });
  });
});
