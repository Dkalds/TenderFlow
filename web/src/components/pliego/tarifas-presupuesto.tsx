"use client";

/**
 * F2.4 — tarifas por perfil y desglose del presupuesto, tal como los extrajo
 * la ficha del pliego (`TenderFactSheet.rate_cards` y `.budget_breakdown`).
 *
 * Cada fila lleva su cita: el criterio de aceptación es «ninguna tarifa sin
 * `EvidenceRef`», y una tarifa que no se puede verificar en el pliego no sirve
 * para fijar un precio. La cita abre la página del pliego con el fragmento
 * resaltado (F2.5).
 *
 * Nada se suma aquí: ni el coste total de las tarifas ni el del presupuesto.
 * El coste que sostiene el margen lo calcula el backend (`margen_implicito`
 * de los escenarios de precio) y sólo cuando hay tarifa **y** horas de todos
 * los perfiles; una suma parcial hecha en cliente sería un margen equivocado
 * presentado como dato (ADR-014).
 */

import * as React from "react";
import { FileSearch } from "lucide-react";
import { PaginaPliegoDialog } from "@/components/pliego/pagina-pliego-dialog";
import { useTenderFactSheet } from "@/hooks/use-tender-fact-sheet";
import type { EvidenceRef, Schemas } from "@/lib/api-types";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

type RateCard = Schemas["RateCardFact"];
type BudgetLine = Schemas["BudgetLineFact"];

const PARTIDA: Record<BudgetLine["category"], string> = {
  salariales: "Costes salariales",
  directos: "Costes directos",
  indirectos: "Costes indirectos",
  beneficio: "Beneficio industrial",
  otro: "Otro",
};

function BotonCita({
  evidencia,
  onVer,
  que,
}: {
  evidencia: readonly EvidenceRef[] | undefined;
  onVer: (cita: EvidenceRef) => void;
  que: string;
}) {
  const cita = evidencia?.[0];
  if (!cita) return <span className="text-muted-foreground">Sin cita</span>;
  return (
    <button
      type="button"
      onClick={() => onVer(cita)}
      aria-label={`Ver la cita de ${que} en el pliego, página ${cita.page_number}`}
      className="inline-flex min-h-6 items-center gap-1 font-medium text-primary hover:underline"
    >
      <FileSearch className="h-3 w-3 shrink-0" aria-hidden="true" />
      p. {cita.page_number}
    </button>
  );
}

export function TarifasPresupuesto({ licitacionId }: { licitacionId: string }) {
  const { data } = useTenderFactSheet(licitacionId);
  const [cita, setCita] = React.useState<EvidenceRef | null>(null);
  const tarifas: RateCard[] = data?.facts?.rate_cards ?? [];
  const partidas: BudgetLine[] = data?.facts?.budget_breakdown ?? [];
  // Sin ficha, o una ficha sin estas dos familias, no pinta nada: la pestaña
  // de la ficha ya dice si falta extraerla.
  if (tarifas.length === 0 && partidas.length === 0) return null;

  return (
    <section aria-labelledby="tarifas-presupuesto" className="space-y-4">
      <h3 id="tarifas-presupuesto" className="text-sm font-semibold">
        Tarifas y desglose del presupuesto del pliego
      </h3>

      {tarifas.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="mb-1.5 text-left text-xs text-muted-foreground">
              Tarifas máximas por perfil. Son techos del pliego, no los costes de tu empresa.
            </caption>
            <thead>
              <tr className="border-b border-border/70 text-muted-foreground">
                <th scope="col" className="py-1.5 pr-3 font-medium">Perfil</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Tarifa máx.</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Horas estimadas</th>
                <th scope="col" className="py-1.5 font-medium">Cita</th>
              </tr>
            </thead>
            <tbody>
              {tarifas.map((tarifa, i) => (
                <tr key={`${tarifa.role}-${i}`} className="border-b border-border/40">
                  <td className="py-1.5 pr-3">{tarifa.role}</td>
                  <td className="tf-tnum py-1.5 pr-3 text-right">
                    {tarifa.max_rate_eur_hour != null ? `${formatCurrency(tarifa.max_rate_eur_hour)}/h` : "—"}
                  </td>
                  <td className="tf-tnum py-1.5 pr-3 text-right">
                    {tarifa.estimated_hours != null ? formatNumber(tarifa.estimated_hours) : "—"}
                  </td>
                  <td className="py-1.5">
                    <BotonCita evidencia={tarifa.evidence} onVer={setCita} que={tarifa.role} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {partidas.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="mb-1.5 text-left text-xs text-muted-foreground">
              Desglose del presupuesto publicado (art. 100 LCSP).
            </caption>
            <thead>
              <tr className="border-b border-border/70 text-muted-foreground">
                <th scope="col" className="py-1.5 pr-3 font-medium">Concepto</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Partida</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Importe</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">%</th>
                <th scope="col" className="py-1.5 font-medium">Cita</th>
              </tr>
            </thead>
            <tbody>
              {partidas.map((partida, i) => (
                <tr key={`${partida.concept}-${i}`} className="border-b border-border/40">
                  <td className="py-1.5 pr-3">{partida.concept}</td>
                  <td className="py-1.5 pr-3 text-muted-foreground">{PARTIDA[partida.category]}</td>
                  <td className="tf-tnum py-1.5 pr-3 text-right">
                    {partida.amount_eur != null ? formatCurrency(partida.amount_eur) : "—"}
                  </td>
                  <td className="tf-tnum py-1.5 pr-3 text-right">
                    {partida.pct != null ? formatPercent(partida.pct) : "—"}
                  </td>
                  <td className="py-1.5">
                    <BotonCita evidencia={partida.evidence} onVer={setCita} que={partida.concept} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PaginaPliegoDialog licitacionId={licitacionId} cita={cita} onClose={() => setCita(null)} />
    </section>
  );
}
