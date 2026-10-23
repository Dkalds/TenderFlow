"use client";

/**
 * Lo que la política de contenido bloqueó en el navegador de los usuarios,
 * agrupado por directiva y origen.
 *
 * Los informes llegan por `POST /security/csp-report` desde el principio y se
 * guardaban en una tabla que ninguna pantalla leía: catorce en una semana
 * (2026-10-09), todos de `frame-src`, que nadie vio. La lectura
 * (`GET /security/csp-violations`) los agrupa como se revisa una CSP —qué
 * directiva bloquea a qué origen— y no informe a informe. Sin IP ni identidad;
 * la página va sin query string.
 *
 * Solo se monta para administradores (la ruta lo exige): quien llama decide, y
 * así la consulta ni sale para quien iba a recibir un 403.
 */

import { useQuery } from "@tanstack/react-query";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { apiGet } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";
import { cn, formatDateTime, formatNumber } from "@/lib/utils";

const LIMITE = 20;
/** Una semana: la ventana que tarda un despliegue en demostrar que arregló algo. */
const DIAS = 7;

export function CspViolacionesCard() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: adminKeys.cspViolations,
    queryFn: () => apiGet("/api/v1/security/csp-violations", { params: { query: { limit: LIMITE, dias: DIAS } } }),
    staleTime: 60_000,
    // El fallo lo dice el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const filas = data?.items ?? [];

  return (
    <Panel>
      <PanelTitle
        title="Bloqueos de la política de contenido"
        hint={`Lo que la CSP ha impedido cargar en los últimos ${data?.dias ?? DIAS} días, por directiva y origen`}
      />
      {isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los bloqueos de la política de contenido"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún bloqueo en la ventana"
          hint="Cuando la política de contenido impida cargar algo, aparecerá aquí con su directiva y su origen."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="text-tf-body w-full min-w-[560px] text-left">
            <caption className="sr-only">Bloqueos de la política de contenido, agrupados</caption>
            <thead className="border-border/70 border-y">
              <tr>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Directiva
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Origen bloqueado
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Página
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2 text-right")}>
                  Veces
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Última vez
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.map((fila) => (
                <tr key={`${fila.directiva}|${fila.origen}`} className="border-border/60 border-b last:border-0">
                  <td className="text-tf-meta px-3 py-2 font-mono">{fila.directiva}</td>
                  <td className="max-w-0 px-3 py-2">
                    <Pista contenido={fila.origen}>
                      <span className="text-tf-meta block truncate font-mono">{fila.origen}</span>
                    </Pista>
                  </td>
                  <td className="max-w-0 px-3 py-2">
                    <Pista contenido={fila.documento ?? undefined}>
                      <span className="text-tf-meta text-muted-foreground block truncate font-mono">
                        {fila.documento ?? "—"}
                      </span>
                    </Pista>
                  </td>
                  <td className="tf-tnum px-3 py-2 text-right font-medium">{formatNumber(fila.ocurrencias)}</td>
                  <td className="tf-tnum text-tf-meta text-muted-foreground px-3 py-2 whitespace-nowrap">
                    {fila.ultima_vez ? formatDateTime(fila.ultima_vez) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
