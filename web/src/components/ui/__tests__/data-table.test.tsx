import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DataTable, IndicadorOrden, type DataTableColumnDef } from "@/components/ui/data-table";

interface Row {
  name: string;
  value: number;
}

const columns: DataTableColumnDef<Row>[] = [
  { accessorKey: "name", header: "Nombre" },
  { accessorKey: "value", header: "Valor" },
];

const data: Row[] = [
  { name: "Beta", value: 2 },
  { name: "Alpha", value: 1 },
];

describe("DataTable", () => {
  it("renders headers and a row per data item", () => {
    render(<DataTable columns={columns} data={data} />);
    expect(screen.getByText("Nombre")).toBeInTheDocument();
    expect(screen.getByText("Valor")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("shows the empty message when there is no data", () => {
    render(<DataTable columns={columns} data={[]} emptyMessage="Nada aquí" />);
    expect(screen.getByText("Nada aquí")).toBeInTheDocument();
  });

  it("toggles sorting when a sortable header is clicked", () => {
    render(<DataTable columns={columns} data={data} />);
    const header = screen.getByText("Nombre").closest("th")!;
    expect(header.getAttribute("aria-sort")).toBe("none");
    fireEvent.click(header);
    expect(header.getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(header);
    expect(header.getAttribute("aria-sort")).toBe("descending");
  });

  it("toggles sorting via the keyboard (Enter)", () => {
    render(<DataTable columns={columns} data={data} />);
    // "Valor" is a numeric column → tanstack sorts descending-first.
    const header = screen.getByText("Valor").closest("th")!;
    expect(header.getAttribute("aria-sort")).toBe("none");
    fireEvent.keyDown(header, { key: "Enter" });
    expect(header.getAttribute("aria-sort")).toBe("descending");
  });

  it("applies getRowClassName and a custom className", () => {
    const { container } = render(
      <DataTable
        columns={columns}
        data={data}
        className="tbl"
        getRowClassName={(row) => (row.original.name === "Beta" ? "is-beta" : undefined)}
      />,
    );
    expect(container.querySelector(".tbl")).not.toBeNull();
    expect(container.querySelector(".is-beta")).not.toBeNull();
  });
});

describe("IndicadorOrden", () => {
  it("la columna activa enseña su sentido, en el color del texto", () => {
    const { container, rerender } = render(<IndicadorOrden direccion="asc" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveClass("text-foreground", "h-3", "w-3");
    rerender(<IndicadorOrden direccion="desc" />);
    expect(container.querySelector("svg")).toHaveClass("text-foreground");
  });

  it("en reposo no se ve con ratón, aparece al pasar o enfocar y se queda tenue en táctil", () => {
    const { container } = render(<IndicadorOrden direccion={false} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveClass(
      "opacity-0",
      "group-hover:opacity-60",
      "group-focus-visible:opacity-60",
      "pointer-coarse:opacity-40",
    );
  });

  it("el orden lo anuncia el aria-sort del th, no el icono", () => {
    render(<DataTable columns={columns} data={data} />);
    const header = screen.getByText("Nombre").closest("th")!;
    expect(header).toHaveClass("group");
    expect(header.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
