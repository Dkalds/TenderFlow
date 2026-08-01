import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const pathnameRef = { current: "/organos" };
vi.mock("next/navigation", () => ({
  usePathname: () => pathnameRef.current,
}));
vi.mock("@/lib/filters", () => ({
  useWithFilters: () => (path: string) => path,
}));

import { Breadcrumb } from "@/components/layout/breadcrumb";

beforeEach(() => {
  pathnameRef.current = "/organos";
});

describe("Breadcrumb", () => {
  it("renders the three real levels of the tree", () => {
    // Espacio › Sección › Página. El nivel Sección faltaba, y es justo el que
    // enlaza la sidebar.
    pathnameRef.current = "/tendencias-cpv";
    render(<Breadcrumb />);

    expect(screen.getByRole("link", { name: "Mercado" })).toHaveAttribute("href", "/resumen");
    expect(screen.getByRole("link", { name: "Tendencias" })).toHaveAttribute("href", "/tendencias");
    expect(screen.getByText("Tendencias CPV")).toBeInTheDocument();
  });

  it("collapses the section level when it duplicates the space name", () => {
    // La sección "Mercado" vive dentro del espacio "Mercado": renderizar los dos
    // daría "Mercado › Mercado › Organos".
    render(<Breadcrumb />);

    expect(screen.getAllByText("Mercado")).toHaveLength(1);
    expect(screen.getByText("Órganos")).toBeInTheDocument();
  });

  it("does not label Admin pages as Mercado", () => {
    // Regresión: `findProductSpace` devolvía Mercado para cualquier ruta que no
    // fuese radar/oportunidades, así que el breadcrumb afirmaba
    // "Mercado › Administración" y enlazaba a /resumen.
    pathnameRef.current = "/administracion";
    render(<Breadcrumb />);

    expect(screen.queryByRole("link", { name: "Mercado" })).not.toBeInTheDocument();
    expect(screen.getByText("Administración")).toBeInTheDocument();
  });

  it("does not label Ops pages as Mercado", () => {
    pathnameRef.current = "/calidad-datos";
    render(<Breadcrumb />);

    expect(screen.queryByRole("link", { name: "Mercado" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ops" })).toBeInTheDocument();
  });

  it("does not label personal pipeline pages as Mercado", () => {
    pathnameRef.current = "/mi-watchlist";
    render(<Breadcrumb />);

    expect(screen.queryByRole("link", { name: "Mercado" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mi Pipeline" })).toBeInTheDocument();
  });

  it("keeps the space level for pages that really belong to one", () => {
    pathnameRef.current = "/radar";
    render(<Breadcrumb />);

    expect(screen.getByRole("link", { name: "Radar" })).toHaveAttribute("href", "/radar");
  });

  it("collapses the section level when it duplicates the page name", () => {
    pathnameRef.current = "/investigador";
    render(<Breadcrumb />);

    // "Investigador › Investigador" no informa de nada.
    expect(screen.getAllByText("Investigador")).toHaveLength(1);
  });

  it("renders nothing for an unknown route", () => {
    pathnameRef.current = "/ruta-que-no-existe";
    const { container } = render(<Breadcrumb />);

    expect(container).toBeEmptyDOMElement();
  });

  it("exposes an accessible name for the landmark", () => {
    render(<Breadcrumb />);

    expect(screen.getByRole("navigation", { name: /Ruta de navegación/ })).toBeInTheDocument();
  });
});
