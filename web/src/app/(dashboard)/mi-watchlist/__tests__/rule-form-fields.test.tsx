import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RuleFormFields } from "../_components/rule-form-fields";
import type { RuleFormState } from "../_hooks/watchlist-rule-types";

const FORM: RuleFormState = {
  keyword: "",
  cpv: "",
  min_importe: "",
  ccaa: "",
  frequency: "daily",
  tecnologia: "",
  organo: "",
  procedimiento: "",
  tipo_contrato: "",
  banda_min: "",
  plazo_min_dias: "",
};

const CATALOGOS = {
  procedimiento: [{ codigo: "6", etiqueta: "Contrato menor", descripcion: "" }],
  tipo_contrato: [
    { codigo: "1", etiqueta: "Suministros", descripcion: "" },
    { codigo: "2", etiqueta: "Servicios", descripcion: "" },
  ],
};

function pinta(valores: Partial<RuleFormState>) {
  render(
    <RuleFormFields
      value={{ ...FORM, ...valores }}
      onChange={vi.fn()}
      ccaaList={["__all__"]}
      catalogos={CATALOGOS}
      idPrefix="t"
    />,
  );
}

describe("RuleFormFields: listas CODICE", () => {
  it("el tipo de contrato y el procedimiento guardan el código y enseñan la etiqueta", () => {
    pinta({ tipo_contrato: "2", procedimiento: "6" });

    expect(screen.getByRole("combobox", { name: "Tipo de contrato" })).toHaveTextContent("Servicios");
    expect(screen.getByRole("combobox", { name: "Procedimiento" })).toHaveTextContent("Contrato menor");
  });

  it("un valor que el catálogo no trae se enseña tal cual, no como «Cualquiera»", () => {
    // Una regla guardada con la palabra del selector antiguo.
    pinta({ tipo_contrato: "servicios" });

    expect(screen.getByRole("combobox", { name: "Tipo de contrato" })).toHaveTextContent("servicios");
  });
});
