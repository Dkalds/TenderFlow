import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { LicitacionPublica } from "@/lib/publico-api";
import { AtribucionFuente } from "../ficha-atribucion";

/**
 * La Ley 37/2007 pide citar la fuente: un anuncio de PSCP no puede atribuirse
 * a PLACSP, que es lo que hacía el bloque con todo lo que no fuera TED.
 */
function lic(fuente: string | null): LicitacionPublica {
  return { fuente, url: null, actualizado: null } as unknown as LicitacionPublica;
}

describe("AtribucionFuente", () => {
  it.each([
    ["pscp", "Plataforma de Serveis de Contractació Pública"],
    ["galicia_rss", "Contratos de Galicia"],
    ["ted", "Diario Oficial de la Unión Europea (TED)"],
    ["placsp", "Plataforma de Contratación del Sector Público"],
  ])("cita %s por su nombre", (fuente, nombre) => {
    render(<AtribucionFuente lic={lic(fuente)} />);
    expect(screen.getByText(nombre)).toBeInTheDocument();
  });

  it("sin fuente no se inventa una", () => {
    render(<AtribucionFuente lic={lic(null)} />);
    expect(screen.queryByText(/Plataforma de Contratación del Sector Público/)).not.toBeInTheDocument();
  });
});
