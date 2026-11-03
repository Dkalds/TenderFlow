"use client";

import { Panel, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { EMPTY, formatNumber, formatPercent } from "@/lib/utils";

import { lecturaActas, type CompanyActaScores } from "./company-profile-types";

/** Una media del acta: la cifra solo si hay actas bastantes; si no, lo dice. */
function MediaActa({ label, criterio }: { label: string; criterio: CompanyActaScores["precio"] }) {
  const actas = `${formatNumber(criterio.actas)} ${criterio.actas === 1 ? "acta" : "actas"}`;
  return criterio.pct_medio == null ? (
    <StatCell label={label} value={EMPTY} hint={`Sin datos suficientes: ${actas}`} />
  ) : (
    <StatCell label={label} value={formatPercent(criterio.pct_medio, 0)} hint={`De los puntos posibles, media de ${actas}`} />
  );
}

/**
 * Dónde puntúa según las actas de la mesa. Va aparte de los cortes porque no
 * sigue el periodo ni los filtros: las actas leídas son pocas (solo las de los
 * expedientes que alguna organización sigue) y partirlas más dejaría cada
 * media por debajo del mínimo.
 */
export function CompanyActas({ acta }: { acta: CompanyActaScores }) {
  const lectura = lecturaActas(acta);
  return (
    <Panel>
      <PanelTitle
        title="Cómo puntúa en las actas"
        hint={`Actas de la mesa leídas, sin los filtros del periodo. Sin media por debajo de ${acta.min_actas} actas.`}
      />
      <StatStrip columns={3}>
        <MediaActa label="Puntos de precio" criterio={acta.precio} />
        <MediaActa label="Puntos técnicos" criterio={acta.tecnica} />
        <StatCell
          label="Actas en que figura"
          value={formatNumber(acta.actas)}
          hint={acta.excluida ? `Excluida en ${formatNumber(acta.excluida)}` : "No consta excluida en ninguna"}
        />
      </StatStrip>
      {lectura ? <p className="mt-3 text-tf-body text-muted-foreground">{lectura}</p> : null}
    </Panel>
  );
}
