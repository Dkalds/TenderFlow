"use client";

/**
 * Lista de resultados de la búsqueda, con la fuente real que devolvió el
 * backend y la exportación de lo que hay en pantalla.
 */

import { Download } from "lucide-react";
import { PanelEmpty } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { exportCSV } from "../_lib/export-csv";
import { sourceHint, sourceLabel } from "../_lib/source-label";
import type { SearchResult } from "../_lib/types";
import { InvestigadorResultCard } from "./investigador-result-card";

interface Props {
  results: SearchResult[];
  /** `source` de la respuesta, no del hit: el backend la devuelve una por búsqueda. */
  source: string | null;
  query: string;
}

export function InvestigadorResults({ results, source, query }: Props) {
  const etiqueta = sourceLabel(source);
  const pista = sourceHint(source);

  return (
    <section aria-labelledby="investigador-resultados" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h2 id="investigador-resultados" className="text-tf-body font-semibold">
            {results.length} {results.length === 1 ? "resultado" : "resultados"}
          </h2>
          {/* La fuente que se pinta es la que devolvió la búsqueda: si no hay
              pliegos indexados, dice «Texto completo» aunque «Tipo de
              coincidencia» esté en «Por significado». La explicación va
              debajo, en texto: un `title` no se lee con el teclado. */}
          {etiqueta && (
            <Badge variant="outline" size="sm">
              {etiqueta}
            </Badge>
          )}
        </div>
        {results.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => exportCSV(results, source)}>
            <Download aria-hidden="true" />
            Exportar CSV
          </Button>
        )}
      </div>
      {pista && <p className="text-tf-meta text-muted-foreground">{pista}</p>}
      {results.length === 0 ? (
        <PanelEmpty
          title="Sin resultados"
          hint="Prueba con otras palabras, acerca «Tipo de coincidencia» a «Por significado» o quita el ámbito en «Opciones avanzadas»."
        />
      ) : (
        results.map((r, i) => (
          <InvestigadorResultCard key={r.id_externo ?? r.id ?? String(i)} result={r} query={query} />
        ))
      )}
    </section>
  );
}
