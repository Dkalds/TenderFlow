/**
 * El presupuesto de una fila del histórico es el que usa su baja.
 *
 * La baja se mide contra el lote: con solo el presupuesto del expediente al
 * lado, una baja del 25 % junto a 100.000 € y 15.000 € adjudicados no cuadraba.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { Table, TableBody, TableRow } from "@/components/ui/table";
import { EMPTY, formatCurrency } from "@/lib/utils";

import { CeldaPresupuesto } from "../company-award-presupuesto";
import type { CompanyAward } from "../company-profile-types";

/** Las líneas de la celda, tal cual: `formatCurrency` separa el símbolo con un espacio duro. */
function lineas(award: CompanyAward): string[] {
  const { container } = render(
    <Table>
      <TableBody>
        <TableRow>
          <CeldaPresupuesto award={award} />
        </TableRow>
      </TableBody>
    </Table>,
  );
  return Array.from(container.querySelectorAll("td p"), (p) => p.textContent ?? "");
}

afterEach(cleanup);

describe("CeldaPresupuesto", () => {
  it("enseña el presupuesto del lote y, debajo, el del expediente", () => {
    expect(lineas({ licitacion_id: "L-1", presupuesto_licitacion: 100_000, presupuesto_comparable: 20_000 })).toEqual(
      [formatCurrency(20_000), `Expediente: ${formatCurrency(100_000)}`],
    );
  });

  it("no repite el expediente si es el mismo número", () => {
    // La base sin IVA y el importe pueden diferir solo en decimales de float4.
    expect(
      lineas({ licitacion_id: "L-2", presupuesto_licitacion: 50_000, presupuesto_comparable: 50_000.000_4 }),
    ).toEqual([formatCurrency(50_000)]);
  });

  it("sin presupuesto de la baja no lo inventa con el del expediente", () => {
    expect(lineas({ licitacion_id: "L-3", presupuesto_licitacion: 80_000 })).toEqual([
      EMPTY,
      `Expediente: ${formatCurrency(80_000)}`,
    ]);
  });
});
