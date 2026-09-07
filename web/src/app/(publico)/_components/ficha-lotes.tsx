import type { LicitacionPublica } from "@/lib/publico-api";
import { formatCurrency } from "@/lib/utils";

/**
 * Lotes del anuncio, tal y como los publica la fuente.
 *
 * `lotes` es opcional en el esquema generado: Pydantic lo declara con
 * `default_factory`, así que no sale como requerido en el OpenAPI. Sin lotes no
 * se pinta nada — ni el título ni la tabla vacía.
 */
export function LotesLicitacion({ lotes }: { lotes: NonNullable<LicitacionPublica["lotes"]> }) {
  if (lotes.length === 0) return null;

  return (
    <>
      <h2 className="font-display mt-12 text-xl font-semibold tracking-[-0.02em]">Lotes ({lotes.length})</h2>
      <div className="border-border/70 bg-card mt-5 overflow-x-auto rounded-xl border px-5 py-2">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="border-border/60 text-muted-foreground border-b text-left text-[11px] tracking-wide uppercase">
              <th className="py-2.5 pr-4 font-medium">Nº</th>
              <th className="py-2.5 pr-4 font-medium">Objeto</th>
              <th className="py-2.5 pr-4 font-medium">CPV</th>
              <th className="py-2.5 font-medium">Importe</th>
            </tr>
          </thead>
          <tbody>
            {lotes.map((lote) => (
              <tr key={lote.numero} className="border-border/30 border-b last:border-b-0">
                <td className="py-2.5 pr-4 font-mono text-xs">{lote.numero}</td>
                <td className="py-2.5 pr-4">{lote.titulo ?? "—"}</td>
                <td className="py-2.5 pr-4 font-mono text-xs">{lote.cpv ?? "—"}</td>
                <td className="tf-tnum py-2.5">{formatCurrency(lote.importe)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
