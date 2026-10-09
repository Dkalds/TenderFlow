"use client";

/**
 * Lista de resultados de la búsqueda: cuántos son, por qué camino llegaron y
 * qué se puede hacer con ellos (exportarlos, o convertir la búsqueda en una
 * alerta de Mi Watchlist).
 */

import Link from "next/link";
import { BellPlus, Download } from "lucide-react";
import { PanelEmpty } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { exportCSV } from "../_lib/export-csv";
import { sourceHint, sourceLabel } from "../_lib/source-label";
import type { SearchResult } from "../_lib/types";
import type { ExpedienteMarcado } from "../_hooks/use-investigador";
import { InvestigadorResultCard } from "./investigador-result-card";

interface Props {
  results: SearchResult[];
  /** `source` de la respuesta, no del resultado: llega una por búsqueda. */
  source: string | null;
  /** Enlace a «Nueva regla» de Mi Watchlist con esta búsqueda ya puesta. */
  enlaceAlerta: string;
  /** La frase traía filtros y se aplicaron: sin resultados, puede ser por eso. */
  hayFiltrosEntendidos: boolean;
  /** El ámbito de la barra está acotando la búsqueda. */
  hayAmbito: boolean;
  onBuscarTalCual: () => void;
  seleccion: ExpedienteMarcado[];
  seleccionLlena: boolean;
  onAlternar: (result: SearchResult) => void;
}

export function InvestigadorResults({
  results,
  source,
  enlaceAlerta,
  hayFiltrosEntendidos,
  hayAmbito,
  onBuscarTalCual,
  seleccion,
  seleccionLlena,
  onAlternar,
}: Props) {
  const etiqueta = sourceLabel(source);
  const pista = sourceHint(source);
  const marcados = new Set(seleccion.map((s) => s.id));

  return (
    <section aria-labelledby="investigador-resultados" className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h2 id="investigador-resultados" className="text-tf-body font-semibold">
            {results.length} {results.length === 1 ? "resultado" : "resultados"}
          </h2>
          {/* La fuente es la que llegó en la respuesta, no la que se esperaba.
              La explicación va debajo, en texto: un `title` no se lee con el
              teclado. */}
          {etiqueta && (
            <Badge variant="outline" size="sm">
              {etiqueta}
            </Badge>
          )}
        </div>
        <div className="flex flex-none items-center gap-1.5">
          {/* La regla se termina de definir en Mi Watchlist, que enseña cuánto
              avisaría antes de guardarla: aquí no se crea nada a ciegas. */}
          <Button asChild variant="outline" size="sm">
            <Link href={enlaceAlerta}>
              <BellPlus aria-hidden="true" />
              Crear alerta
            </Link>
          </Button>
          {results.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => exportCSV(results, source)}>
              <Download aria-hidden="true" />
              Exportar CSV
            </Button>
          )}
        </div>
      </div>
      {pista && results.length > 0 && <p className="text-tf-meta text-muted-foreground">{pista}</p>}
      {results.length === 0 ? (
        <PanelEmpty
          title="Sin resultados"
          hint={
            hayFiltrosEntendidos
              ? "Los filtros que se leyeron en tu frase pueden estar dejándolo todo fuera."
              : hayAmbito
                ? "Prueba con otras palabras, o quita el ámbito en «Opciones avanzadas»."
                : "Prueba con otras palabras, o con menos: basta con que aparezca alguna."
          }
          action={
            hayFiltrosEntendidos ? (
              <Button variant="outline" size="sm" onClick={onBuscarTalCual}>
                Buscar el texto tal cual
              </Button>
            ) : undefined
          }
        />
      ) : (
        results.map((r) => (
          <InvestigadorResultCard
            key={r.id_externo}
            result={r}
            marcado={marcados.has(r.id_externo)}
            sinHueco={seleccionLlena && !marcados.has(r.id_externo)}
            onAlternar={onAlternar}
          />
        ))
      )}
    </section>
  );
}
