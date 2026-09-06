/**
 * Las ramas condicionales que la partición de `empresas/page.tsx` sacó del
 * monolito a piezas propias.
 *
 * Son las que no ve un E2E de humo: el aviso de cobertura solo aparece por
 * debajo del umbral, los desgloses tienen un corte y un estado vacío, y el
 * bloque de identidad relacional se oculta entero cuando no hay nada que
 * contar. Al vivir cada una en su fichero, un `&&` perdido en el reparto no
 * rompería ninguna otra prueba.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { EmpresasCobertura } from "../_components/empresas-cobertura";
import { EmpresaRelaciones } from "../_components/empresa-relaciones";
import { MiniRanking } from "../_components/mini-ranking";
import type { EmpresaDetail, EmpresaStats, RankingRow } from "../_lib/types";

function stats(pct_importe: number): EmpresaStats {
  return {
    adjudicaciones_total: 24500,
    adjudicaciones_enlazadas: 21300,
    pct_filas: 90,
    pct_importe,
    empresas: 42,
    revisiones_pendientes: 3,
  };
}

function detail(patch: Partial<EmpresaDetail> = {}): EmpresaDetail {
  return {
    empresa_id: 1,
    nombre_canonico: "INDRA",
    nif_canonico: "A28599033",
    es_ute: 0,
    grupo: null,
    aliases: [],
    ute_miembros: [],
    participa_en_utes: [],
    ...patch,
  };
}

function alias(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    alias_normalizado: `ALIAS ${i}`,
    nif_variante: null,
    fuente: "placsp",
  }));
}

describe("EmpresasCobertura", () => {
  it("avisa cuando el importe resuelto no llega al 95%", () => {
    render(<EmpresasCobertura stats={stats(87.4)} vigiladas={2} onVerRevisiones={undefined} />);
    expect(screen.getByText("BAJO 95%")).toBeTruthy();
    // ADR-014: el porcentaje nunca va sin su denominador.
    expect(screen.getByText("21.300 de 24.500 adjudicaciones")).toBeTruthy();
  });

  it("no avisa cuando el importe resuelto llega al umbral", () => {
    render(<EmpresasCobertura stats={stats(95)} vigiladas={0} onVerRevisiones={undefined} />);
    expect(screen.queryByText("BAJO 95%")).toBeNull();
  });

  it("sin datos aún no inventa cobertura: pinta el marcador de carga", () => {
    render(<EmpresasCobertura stats={undefined} vigiladas={0} onVerRevisiones={undefined} />);
    expect(screen.queryByText("BAJO 95%")).toBeNull();
    expect(screen.getAllByText("…").length).toBe(3);
  });

  it("la celda de revisiones solo es pulsable si hay algo pendiente", () => {
    const { rerender } = render(
      <EmpresasCobertura stats={stats(99)} vigiladas={0} onVerRevisiones={undefined} />,
    );
    expect(screen.getByText("nada pendiente")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();

    rerender(<EmpresasCobertura stats={stats(99)} vigiladas={0} onVerRevisiones={() => {}} />);
    expect(screen.getByText("hay matches dudosos por resolver")).toBeTruthy();
    expect(screen.getByRole("button")).toBeTruthy();
  });
});

describe("MiniRanking", () => {
  const filas = (n: number): RankingRow[] =>
    Array.from({ length: n }, (_, i) => ({ label: `Fila ${i}`, contratos: i, importe: i * 100 }));

  it("dice que no hay datos en vez de pintar una lista vacía", () => {
    render(<MiniRanking title="Por territorio" rows={[]} />);
    expect(screen.getByText("Sin datos.")).toBeTruthy();
  });

  it("corta en seis filas y no pinta las demás", () => {
    render(<MiniRanking title="Por familia CPV" rows={filas(9)} />);
    expect(screen.getByText("Fila 5")).toBeTruthy();
    expect(screen.queryByText("Fila 6")).toBeNull();
  });
});

describe("EmpresaRelaciones", () => {
  it("no pinta nada cuando no hay UTEs ni más de un alias", () => {
    const { container } = render(<EmpresaRelaciones detail={detail({ aliases: alias(1) })} />);
    expect(container.textContent).toBe("");
  });

  it("pinta las dos direcciones de la UTE por separado", () => {
    render(
      <EmpresaRelaciones
        detail={detail({
          ute_miembros: [{ empresa_id: 2, nombre_canonico: "SOCIA A" }],
          participa_en_utes: [{ empresa_id: 3, nombre_canonico: "UTE OBRAS" }],
        })}
      />,
    );
    expect(screen.getByText("Miembros de la UTE")).toBeTruthy();
    expect(screen.getByText("SOCIA A")).toBeTruthy();
    expect(screen.getByText("Participa en UTEs")).toBeTruthy();
    expect(screen.getByText("UTE OBRAS")).toBeTruthy();
  });

  it("resume los alias que no caben en vez de ocultarlos sin decirlo", () => {
    render(<EmpresaRelaciones detail={detail({ aliases: alias(15) })} />);
    expect(screen.getByText("Aliases vistos en fuente (15)")).toBeTruthy();
    expect(screen.getByText("ALIAS 11")).toBeTruthy();
    expect(screen.queryByText("ALIAS 12")).toBeNull();
    expect(screen.getByText("+3 más")).toBeTruthy();
  });
});
