/**
 * Tests for src/components/markdown-answer.tsx — Markdown renderer +
 * linkifier de IDs de expediente.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownAnswer, clasificarEnlace, linkifyExpedientes } from "@/components/markdown-answer";

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

describe("clasificarEnlace", () => {
  it.each([
    ["/detalle?lic=ABC-1-X", "interno"],
    ["#seccion", "interno"],
    ["https://www.contrataciondelestado.es/x", "externo"],
    ["http://example.org", "externo"],
    ["mailto:hola@example.org", "correo"],
  ])("deja pasar %s como %s", (href, tipo) => {
    expect(clasificarEnlace(href)).toBe(tipo);
  });

  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "java" + String.fromCharCode(10) + "script:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:x",
    "file:///etc/passwd",
    "//evil.example/login",
    // `\` y tabulador: el navegador los reinterpreta y "/…/evil" acaba siendo "//evil".
    "/" + String.fromCharCode(92) + "evil.example",
    "/" + String.fromCharCode(9) + "/evil.example",
    "evil.example/login",
    "ftp://evil.example",
    "",
    undefined,
  ])("descarta %j", (href) => {
    expect(clasificarEnlace(href)).toBeNull();
  });
});

describe("MarkdownAnswer: enlaces del modelo", () => {
  it("marca los externos como no fiables y los abre fuera", () => {
    render(<MarkdownAnswer text="[ver oferta](https://dominio-atacante.example/p)" />);
    const link = screen.getByRole("link", { name: "ver oferta" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
  });

  it("no pinta como enlace un esquema peligroso: queda solo el texto", () => {
    render(<MarkdownAnswer text="[pulsa aquí](javascript:alert(1)) y [otro](//evil.example)" />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("pulsa aquí")).toBeInTheDocument();
  });

  it("no pinta imágenes remotas", () => {
    const { container } = render(<MarkdownAnswer text="![baliza](https://t.example/p.gif)" />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("los enlaces internos a un expediente siguen en la misma pestaña", () => {
    render(<MarkdownAnswer text="Ver ABC-123-XYZ-001" />);
    const link = screen.getByRole("link", { name: "ABC-123-XYZ-001" });
    expect(link).not.toHaveAttribute("target");
  });
});
