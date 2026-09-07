"use client";

/**
 * Lista de resultados de la búsqueda semántica, con la fuente real que devolvió
 * el backend y la exportación de lo que hay en pantalla.
 */

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">{results.length} resultados encontrados</h2>
          {/* La fuente que se pinta es la que devolvió el backend: si no
              hay pliegos embebidos, esto dice «Texto completo» aunque el
              deslizador semántico esté al máximo. */}
          {etiqueta && (
            <Badge variant="outline" className="text-xs" title={pista ?? undefined}>
              {etiqueta}
            </Badge>
          )}
        </div>
        {results.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => exportCSV(results, source)}>
            <Download className="mr-2 h-4 w-4" />
            Exportar CSV
          </Button>
        )}
      </div>
      {pista && <p className="text-muted-foreground text-xs">{pista}</p>}
      {results.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="text-muted-foreground py-8 text-center">
            No se encontraron resultados para tu búsqueda.
          </CardContent>
        </Card>
      ) : (
        results.map((r, i) => (
          <InvestigadorResultCard key={r.id_externo ?? r.id ?? String(i)} result={r} query={query} />
        ))
      )}
    </div>
  );
}
