"use client";

import { Panel, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { EMPTY, formatNumber, formatPercent } from "@/lib/utils";

import { lecturaActas, type CompanyActaScores } from "./company-profile-types";

/**
 * Una media del acta: la cifra solo si hay actas bastantes; si no, cuántas hay.
 * Pistas cortas a propósito: en móvil la celda va a media anchura y se truncan.
 */
function MediaActa({ label, criterio }: { label: string; criterio: CompanyActaScores["precio"] }) {
  const actas = `${formatNumber(criterio.actas)} ${criterio.actas === 1 ? "acta" : "actas"}`;
  return criterio.pct_medio == null ? (
    <StatCell label={label} value={EMPTY} hint={`Solo ${actas}`} />
  ) : (
    <StatCell label={label} value={formatPercent(criterio.pct_medio, 0)} hint={`Media de ${actas}`} />
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
      <PanelTitle title="Cómo puntúa en las actas" />
      <StatStrip columns={3}>
        <MediaActa label="Puntos de precio" criterio={acta.precio} />
        <MediaActa label="Puntos técnicos" criterio={acta.tecnica} />
        <StatCell
          label="Actas en que figura"
          value={formatNumber(acta.actas)}
          hint={acta.excluida ? `Excluida en ${formatNumber(acta.excluida)}` : "Nunca excluida"}
        />
      </StatStrip>
      {lectura ? <p className="mt-3 text-tf-body">{lectura}</p> : null}
      {/* Nota y no `hint` del título: `PanelTitle` trunca la pista, que es para un recuento. */}
      <p className="mt-2 text-tf-meta text-muted-foreground">
        Parte de los puntos posibles que saca, de media por acta, en las actas de la mesa ya leídas. No sigue los
        filtros del periodo, y con menos de {acta.min_actas} actas no hay media.
      </p>
    </Panel>
  );
}
