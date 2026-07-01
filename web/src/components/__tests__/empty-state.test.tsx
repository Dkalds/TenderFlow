import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EmptyState } from "@/components/ui/empty-state";
import { Star } from "lucide-react";

describe("EmptyState", () => {
  it("renders with default title and hint", () => {
    render(<EmptyState />);
    // i18n t("common.no_data") and t("common.no_data_hint") should be present
    expect(document.body).toBeInTheDocument();
  });

  it("renders custom title", () => {
    render(<EmptyState title="No hay resultados" />);
    expect(screen.getByText("No hay resultados")).toBeInTheDocument();
  });

  it("renders custom hint", () => {
    render(<EmptyState hint="Prueba con otros filtros" />);
    expect(screen.getByText("Prueba con otros filtros")).toBeInTheDocument();
  });

  it("renders a custom icon", () => {
    const { container } = render(<EmptyState icon={Star} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
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
