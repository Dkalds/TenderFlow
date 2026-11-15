import { TableCell } from "@/components/ui/table";
import { formatCurrency } from "@/lib/utils";

import type { CompanyAward } from "./company-profile-types";

/**
 * Presupuesto de una fila del histórico: el que usa su baja (el del lote, si lo
 * hay) y, debajo, el del expediente cuando es otro número. Sin esa línea, una
 * baja del 25 % junto a un presupuesto de 100.000 € y un adjudicado de 15.000 €
 * no se podía reconstruir.
 */
export function CeldaPresupuesto({ award }: { award: CompanyAward }) {
  const presupuesto = formatCurrency(award.presupuesto_comparable);
  const expediente = formatCurrency(award.presupuesto_licitacion);
  // Se comparan formateados: la base sin IVA y el importe difieren en decimales de float4.
  const otroExpediente = award.presupuesto_licitacion != null && expediente !== presupuesto;
  return (
    <TableCell numeric>
      <p>{presupuesto}</p>
      {otroExpediente ? <p className="text-tf-meta text-muted-foreground">Expediente: {expediente}</p> : null}
    </TableCell>
  );
}
