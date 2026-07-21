/**
 * Tests for src/components/markdown-answer.tsx — Markdown renderer +
 * linkifier de IDs de expediente.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownAnswer, linkifyExpedientes } from "@/components/markdown-answer";

describe("linkifyExpedientes", () => {
  it("rewrites expediente-like tokens as markdown links", () => {
    expect(linkifyExpedientes("Ver ABC-123-XYZ-001 hoy")).toBe(
      "Ver [ABC-123-XYZ-001](/detalle?lic=ABC-123-XYZ-001) hoy",
    );
  });

  it("leaves existing markdown links untouched (no double-linking)", () => {
    const text = "Ya enlazado: [ABC-123-XYZ](/detalle?lic=ABC-123-XYZ)";
    expect(linkifyExpedientes(text)).toBe(text);
  });

  it("leaves inline code untouched", () => {
    const text = "Código: `ABC-123-XYZ`";
    expect(linkifyExpedientes(text)).toBe(text);
  });

  it("ignores plain words without the id shape", () => {
    const text = "S/4HANA y consultoría sin ids";
    expect(linkifyExpedientes(text)).toBe(text);
  });
});

describe("MarkdownAnswer", () => {
  it("renders expediente ids as links to /detalle", () => {
    render(<MarkdownAnswer text="La licitación ABC-123-XYZ-001 fue adjudicada." />);
    const link = screen.getByRole("link", { name: "ABC-123-XYZ-001" });
    expect(link).toHaveAttribute("href", "/detalle?lic=ABC-123-XYZ-001");
  });

  it("renders markdown headings and tables", () => {
    const md = ["## Qué se licita", "", "| Expediente | Órgano |", "| --- | --- |", "| EXP-1-A | AEAT |"].join("\n");
    render(<MarkdownAnswer text={md} />);

    expect(screen.getByText("Qué se licita")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("AEAT")).toBeInTheDocument();
  });

  it("renders plain paragraphs", () => {
    render(<MarkdownAnswer text="Respuesta simple." />);
    expect(screen.getByText("Respuesta simple.")).toBeInTheDocument();
  });
});
