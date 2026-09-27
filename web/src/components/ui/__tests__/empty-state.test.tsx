import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EmptyState } from "@/components/ui/empty-state";
import { Star } from "lucide-react";

describe("EmptyState", () => {
  it("no inventa un título ni una pista genéricos", () => {
    // El «Sin datos» con bandeja salía idéntico en decenas de paneles y no
    // decía qué faltaba: cada llamada pasa los suyos.
    render(<EmptyState />);
    expect(screen.queryByText("Sin datos")).not.toBeInTheDocument();
    expect(screen.queryByText(/No hay información disponible/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("delega en PanelEmpty: sin baldosa de icono tintada", () => {
    const { container } = render(<EmptyState title="Sin favoritos" hint="Marca una licitación con la estrella." />);
    expect(container.querySelector(".rounded-2xl")).toBeNull();
    expect(container.innerHTML).not.toMatch(/bg-primary/);
  });

  it("renders custom title", () => {
    render(<EmptyState title="No hay resultados" />);
    expect(screen.getByText("No hay resultados")).toBeInTheDocument();
  });

  it("renders custom hint", () => {
    render(<EmptyState hint="Prueba con otros filtros" />);
    expect(screen.getByText("Prueba con otros filtros")).toBeInTheDocument();
  });

  it("renders a custom icon, small and inline with the title", () => {
    const { container } = render(<EmptyState icon={Star} title="Sin favoritos" hint="Marca una con la estrella." />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveClass("h-4", "w-4", "text-muted-foreground");
  });

  it("renders an action button when actionLabel and onAction are provided", () => {
    const handler = vi.fn();
    render(<EmptyState actionLabel="Reintentar" onAction={handler} />);
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("calls onAction when the button is clicked", () => {
    const handler = vi.fn();
    render(<EmptyState actionLabel="Reintentar" onAction={handler} />);
    fireEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not render action button when only actionLabel is provided", () => {
    render(<EmptyState actionLabel="Reintentar" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not render action button when only onAction is provided", () => {
    render(<EmptyState onAction={vi.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not render hint when hint is empty string", () => {
    render(<EmptyState title="Title" hint="" />);
    // Only the title should be in a <p> tag
    const paragraphs = document.querySelectorAll("p");
    expect(paragraphs).toHaveLength(1);
  });

  it("has role=status for accessibility", () => {
    render(<EmptyState />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("applies custom className to wrapper", () => {
    render(<EmptyState className="mt-8" />);
    expect(screen.getByRole("status")).toHaveClass("mt-8");
  });
});
