/**
 * `ChipBanda`: la banda de puntuación dibujada una sola vez, sobre los tokens
 * `--score-*`. Además del marcado, se mide el contraste que promete su
 * comentario: texto de la banda sobre su tinte al 10 % encima de la tarjeta, y
 * «Caliente» sin relleno en el tema oscuro.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChipBanda, esBandaConocida } from "@/components/console/chip-banda";

const BANDAS = [
  ["Caliente", "score-hot"],
  ["Atractiva", "score-warm"],
  ["Tibia", "score-cold"],
  ["Descarte", "score-skip"],
] as const;

describe("ChipBanda", () => {
  it.each(BANDAS)("%s se pinta con su token (--%s), sin estilo inline", (banda, token) => {
    render(<ChipBanda banda={banda} />);
    const chip = screen.getByText(banda);
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveAttribute("data-slot", "chip-banda");
    expect(chip.className).toContain(`text-[hsl(var(--${token}))]`);
    expect(chip.className).toContain(`bg-[hsl(var(--${token})/0.1)]`);
    expect(chip.className).toContain(`border-[hsl(var(--${token})/0.3)]`);
    expect(chip).not.toHaveAttribute("style");
  });

  it("sin banda dice «Sin puntuar» con el color de descarte", () => {
    render(<ChipBanda banda={null} />);
    expect(screen.getByText("Sin puntuar").className).toContain("--score-skip");
  });

  it("una banda que no conoce se pinta tal cual, con el color neutro de descarte", () => {
    render(<ChipBanda banda="Otra" />);
    expect(screen.getByText("Otra").className).toContain("--score-skip");
  });

  it("no es la semántica de error: «Caliente» no usa destructive", () => {
    render(<ChipBanda banda="Caliente" />);
    expect(screen.getByText("Caliente").className).not.toMatch(/destructive/);
  });

  it("reenvía atributos (aria-label, className) y admite la talla md", () => {
    render(<ChipBanda banda="Tibia" size="md" aria-label="Puntuación: Tibia" className="ml-2" />);
    const chip = screen.getByLabelText("Puntuación: Tibia");
    expect(chip).toHaveClass("ml-2", "text-tf-meta");
  });

  it("la talla por defecto es la de filas: 11 px", () => {
    render(<ChipBanda banda="Tibia" />);
    expect(screen.getByText("Tibia")).toHaveClass("h-5", "text-tf-micro");
  });

  it("en el tema oscuro, «Caliente» pierde el relleno y el resto lo conserva", () => {
    render(
      <>
        <ChipBanda banda="Caliente" />
        <ChipBanda banda="Atractiva" />
      </>,
    );
    expect(screen.getByText("Caliente")).toHaveClass("dark:bg-transparent");
    expect(screen.getByText("Atractiva")).not.toHaveClass("dark:bg-transparent");
  });
});

describe("esBandaConocida", () => {
  it("reconoce las cuatro bandas de la API y nada más", () => {
    for (const [banda] of BANDAS) expect(esBandaConocida(banda)).toBe(true);
    expect(esBandaConocida("caliente")).toBe(false);
    expect(esBandaConocida("toString")).toBe(false);
    expect(esBandaConocida(null)).toBe(false);
    expect(esBandaConocida(undefined)).toBe(false);
  });
});

/* ── Contraste del chip ─────────────────────────────────────────────── */

const CSS = readFileSync(
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../app/globals.css"),
  "utf8",
);

type Rgb = readonly [number, number, number];

function color(bloque: ":root" | ".dark", nombre: string): Rgb {
  const inicio = CSS.indexOf(`  ${bloque} {`);
  const cuerpo = CSS.slice(inicio, CSS.indexOf("\n  }", inicio));
  const valor = cuerpo.match(new RegExp(`--${nombre}:\\s*([^;]+);`))?.[1];
  if (!valor) throw new Error(`--${nombre} no está en ${bloque}`);
  const [h, s, l] = valor.replace(/%/g, "").trim().split(/\s+/).map(Number);
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
  const canal = (n: number) => {
    const k = (n + h / 30) % 12;
    return l / 100 - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
  };
  return [canal(0), canal(8), canal(4)];
}

function luminancia(c: Rgb): number {
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a: Rgb, b: Rgb): number {
  const [claro, oscuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x);
  return (claro + 0.05) / (oscuro + 0.05);
}

function tinte(frente: Rgb, fondo: Rgb, alfa: number): Rgb {
  return [0, 1, 2].map((i) => frente[i] * alfa + fondo[i] * (1 - alfa)) as unknown as Rgb;
}

describe("contraste del chip sobre la tarjeta (4,5:1)", () => {
  it.each(BANDAS)("tema claro: %s sobre su tinte al 10 %%", (_banda, token) => {
    const texto = color(":root", token);
    expect(ratio(texto, tinte(texto, color(":root", "card"), 0.1))).toBeGreaterThanOrEqual(4.5);
  });

  it.each(BANDAS.filter(([banda]) => banda !== "Caliente"))(
    "tema oscuro: %s sobre su tinte al 10 %%",
    (_banda, token) => {
      const texto = color(".dark", token);
      expect(ratio(texto, tinte(texto, color(".dark", "card"), 0.1))).toBeGreaterThanOrEqual(4.5);
    },
  );

  it("tema oscuro: «Caliente» necesita ir sin relleno, y sin él pasa", () => {
    const texto = color(".dark", "score-hot");
    const tarjeta = color(".dark", "card");
    expect(ratio(texto, tinte(texto, tarjeta, 0.1))).toBeLessThan(4.5);
    expect(ratio(texto, tarjeta)).toBeGreaterThanOrEqual(4.5);
  });
});
