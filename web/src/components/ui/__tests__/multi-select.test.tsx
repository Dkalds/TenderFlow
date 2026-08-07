import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MultiSelect } from "@/components/ui/multi-select";

const CCAA = ["Andalucía", "Cataluña", "Comunidad de Madrid", "País Vasco"];

function open(label = "Comunidad autónoma") {
  fireEvent.click(screen.getByLabelText(label));
}

describe("MultiSelect", () => {
  it("el disparador muestra el placeholder cuando no hay selección", () => {
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={[]}
        onChange={vi.fn()}
        placeholder="Añadir CCAA…"
      />,
    );
    expect(screen.getByLabelText("Comunidad autónoma")).toHaveTextContent("Añadir CCAA…");
  });

  it("el disparador refleja cuántas opciones hay seleccionadas", () => {
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={["Cataluña", "País Vasco"]}
        onChange={vi.fn()}
        placeholder="Añadir CCAA…"
      />,
    );
    // El `<select value="">` que esto sustituye nunca mostraba lo elegido.
    expect(screen.getByLabelText("Comunidad autónoma")).toHaveTextContent("2 seleccionadas");
  });

  it("marcar una opción la añade a la selección", () => {
    const onChange = vi.fn();
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={["Cataluña"]}
        onChange={onChange}
        placeholder="Añadir CCAA…"
      />,
    );
    open();
    fireEvent.click(screen.getByRole("option", { name: "País Vasco" }));
    expect(onChange).toHaveBeenCalledWith(["Cataluña", "País Vasco"]);
  });

  it("desmarcar una opción seleccionada la quita desde el propio control", () => {
    const onChange = vi.fn();
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={["Cataluña", "País Vasco"]}
        onChange={onChange}
        placeholder="Añadir CCAA…"
      />,
    );
    open();
    fireEvent.click(screen.getByRole("option", { name: "Cataluña" }));
    expect(onChange).toHaveBeenCalledWith(["País Vasco"]);
  });

  it("la búsqueda ignora tildes: 'andalucia' encuentra 'Andalucía'", () => {
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={[]}
        onChange={vi.fn()}
        placeholder="Añadir CCAA…"
      />,
    );
    open();
    fireEvent.change(screen.getByLabelText("Buscar en Comunidad autónoma"), {
      target: { value: "andalucia" },
    });
    expect(screen.getByRole("option", { name: "Andalucía" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Cataluña" })).not.toBeInTheDocument();
  });

  it("informa cuando la búsqueda no encuentra nada", () => {
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={[]}
        onChange={vi.fn()}
        placeholder="Añadir CCAA…"
      />,
    );
    open();
    fireEvent.change(screen.getByLabelText("Buscar en Comunidad autónoma"), {
      target: { value: "zzz" },
    });
    expect(screen.getByText("Sin coincidencias")).toBeInTheDocument();
  });

  it("en modo single, elegir reemplaza la selección en vez de acumular", () => {
    const onChange = vi.fn();
    render(
      <MultiSelect
        aria-label="Tecnología"
        options={["SAP", "Salesforce"]}
        selected={["SAP"]}
        onChange={onChange}
        placeholder="Todas"
        single
      />,
    );
    open("Tecnología");
    fireEvent.click(screen.getByRole("option", { name: "Salesforce" }));
    expect(onChange).toHaveBeenCalledWith(["Salesforce"]);
  });

  it("el listbox declara si admite selección múltiple", () => {
    render(
      <MultiSelect
        aria-label="Comunidad autónoma"
        options={CCAA}
        selected={[]}
        onChange={vi.fn()}
        placeholder="Añadir CCAA…"
      />,
    );
    open();
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-multiselectable", "true");
  });
});
