"use client";

/**
 * Lo que falla en el navegador de los usuarios, agrupado por huella.
 *
 * La API los guarda desde 2026-09 (`GET /security/client-errors`) con «un
 * destino que alguien mira», y ese destino no existía: la tabla se llenaba y
 * ninguna pantalla la leía. Las filas llevan huella, ruta y mensaje; sin IP,
 * sin correo y sin query string.
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

export function ErroresNavegadorCard() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: adminKeys.clientErrors,
    queryFn: () => apiGet("/api/v1/security/client-errors", { params: { query: { limit: LIMITE } } }),
    staleTime: 60_000,
    // El fallo lo dice el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const filas = data?.items ?? [];

  return (
    <Panel>
      <PanelTitle
        title="Errores en el navegador"
        hint="Fallos de JavaScript que han visto los usuarios, agrupados por huella"
      />
      {isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los errores del navegador"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún error registrado"
          hint="Cuando una pantalla falle en el navegador de alguien, aparecerá aquí con su ruta."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-tf-body">
            <caption className="sr-only">Errores de JavaScript del navegador, agrupados</caption>
            <thead className="border-y border-border/70">
              <tr>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Mensaje
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Ruta
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
                <tr key={fila.fingerprint} className="border-b border-border/60 last:border-0">
                  <td className="max-w-0 px-3 py-2">
                    <Pista contenido={fila.mensaje ?? undefined}>
                      <span className="block truncate">{fila.mensaje ?? "sin mensaje"}</span>
                    </Pista>
                  </td>
                  <td className="px-3 py-2 font-mono text-tf-meta text-muted-foreground">
                    {fila.ruta ?? "—"}
                  </td>
                  <td className="tf-tnum px-3 py-2 text-right font-medium">
                    {formatNumber(fila.ocurrencias)}
                  </td>
                  <td className="tf-tnum whitespace-nowrap px-3 py-2 text-tf-meta text-muted-foreground">
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
