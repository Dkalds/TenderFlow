import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
  CABECERA_COLUMNA,
} from "@/components/ui/table";

describe("Table components", () => {
  it("renders a full table without crashing", () => {
    render(
      <Table>
        <TableCaption>Listado de licitaciones</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Nombre</TableHead>
            <TableHead>Importe</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>Proyecto A</TableCell>
            <TableCell>10.000 €</TableCell>
          </TableRow>
          <TableRow>
            <TableCell>Proyecto B</TableCell>
            <TableCell>25.000 €</TableCell>
          </TableRow>
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell>Total</TableCell>
            <TableCell>35.000 €</TableCell>
          </TableRow>
        </TableFooter>
      </Table>,
    );

    expect(screen.getByText("Listado de licitaciones")).toBeInTheDocument();
    expect(screen.getByText("Nombre")).toBeInTheDocument();
    expect(screen.getByText("Proyecto A")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("Table renders a table element inside a scroll container", () => {
    const { container } = render(<Table />);
    expect(container.querySelector("table")).toBeInTheDocument();
  });

  it("TableHeader renders a thead element", () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Col</TableHead>
          </TableRow>
        </TableHeader>
      </Table>,
    );
    expect(document.querySelector("thead")).toBeInTheDocument();
  });

  it("TableBody renders a tbody element", () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>data</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    );
    expect(document.querySelector("tbody")).toBeInTheDocument();
  });

  it("TableFooter renders a tfoot element", () => {
    render(
      <Table>
        <TableFooter>
          <TableRow>
            <TableCell>footer</TableCell>
          </TableRow>
        </TableFooter>
      </Table>,
    );
    expect(document.querySelector("tfoot")).toBeInTheDocument();
  });

  it("TableCaption renders a caption element", () => {
    render(
      <Table>
        <TableCaption>Caption text</TableCaption>
      </Table>,
    );
    expect(document.querySelector("caption")).toBeInTheDocument();
  });

  it("applies custom className to Table", () => {
    const { container } = render(<Table className="custom-table" />);
    expect(container.querySelector("table")).toHaveClass("custom-table");
  });

  it("applies custom className to TableRow", () => {
    render(
      <Table>
        <TableBody>
          <TableRow className="highlighted">
            <TableCell>x</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    );
    expect(document.querySelector("tr")).toHaveClass("highlighted");
  });

  it("forwards ref on Table", () => {
    const ref = { current: null as HTMLTableElement | null };
    render(<Table ref={ref} />);
    expect(ref.current?.tagName).toBe("TABLE");
  });
});

describe("CABECERA_COLUMNA", () => {
  it("TableHead la usa: sans en versal a 11 px, sin mono", () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Órgano</TableHead>
          </TableRow>
        </TableHeader>
      </Table>,
    );
    const th = screen.getByText("Órgano");
    for (const clase of CABECERA_COLUMNA.split(" ")) expect(th).toHaveClass(clase);
    expect(th.className).not.toMatch(/font-mono|text-\[/);
  });

  it("es la única versal: sans, 11 px y un tracking corto", () => {
    expect(CABECERA_COLUMNA).toContain("uppercase");
    expect(CABECERA_COLUMNA).toContain("text-tf-micro");
    expect(CABECERA_COLUMNA).not.toContain("font-mono");
  });
});

describe("TableCell numeric", () => {
  it("alinea a la derecha las columnas de cifras sin pasar la prop al DOM", () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell numeric>1.000 €</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    );
    const td = screen.getByText("1.000 €");
    expect(td).toHaveClass("text-right");
    expect(td).not.toHaveAttribute("numeric");
  });
});
