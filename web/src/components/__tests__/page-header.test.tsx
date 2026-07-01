import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "@/components/layout/page-header";

describe("PageHeader", () => {
  it("renders the title", () => {
    render(<PageHeader title="Resumen general" />);
    expect(screen.getByRole("heading", { name: "Resumen general" })).toBeInTheDocument();
  });

  it("renders a string title in h1", () => {
    render(<PageHeader title="Mi título" />);
    const h1 = document.querySelector("h1");
    expect(h1?.textContent).toBe("Mi título");
  });

  it("renders description when provided", () => {
    render(<PageHeader title="T" description="Descripción detallada" />);
    expect(screen.getByText("Descripción detallada")).toBeInTheDocument();
  });

  it("does not render description when omitted", () => {
    render(<PageHeader title="T" />);
    const paragraphs = document.querySelectorAll("p");
    expect(paragraphs).toHaveLength(0);
  });

  it("renders the eyebrow label when provided", () => {
    render(<PageHeader title="T" eyebrow="MÓDULO" />);
    expect(screen.getByText("MÓDULO")).toBeInTheDocument();
  });

  it("does not render eyebrow when omitted", () => {
    const { container } = render(<PageHeader title="T" />);
    // eyebrow renders in a <p> with uppercase class; without it there should be no eyebrow p
    expect(container.querySelectorAll("p")).toHaveLength(0);
  });

  it("renders actions slot when provided", () => {
    render(
      <PageHeader title="T" actions={<button>Export</button>} />,
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
  });

  it("does not render actions container when omitted", () => {
    render(<PageHeader title="T" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders a header element as root", () => {
    render(<PageHeader title="T" />);
    expect(document.querySelector("header")).toBeInTheDocument();
  });

  it("applies custom className to the header element", () => {
    render(<PageHeader title="T" className="my-custom" />);
    expect(document.querySelector("header")).toHaveClass("my-custom");
  });

  it("renders all parts together correctly", () => {
    render(
      <PageHeader
        title="Análisis"
        description="Vista de licitaciones"
        eyebrow="DASHBOARD"
        actions={<button>Exportar</button>}
      />,
    );
    expect(screen.getByText("Análisis")).toBeInTheDocument();
    expect(screen.getByText("Vista de licitaciones")).toBeInTheDocument();
    expect(screen.getByText("DASHBOARD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
  });
});
