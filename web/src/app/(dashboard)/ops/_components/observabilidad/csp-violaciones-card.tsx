"use client";

/**
 * Lo que la política CSP bloquea en el navegador de los usuarios, agrupado por
 * directiva y origen.
 *
 * `POST /security/csp-report` lo guarda desde 2026-06 y ninguna pantalla lo
 * leía. Cada fila es una decisión: un dominio que falta en la política o un
 * recurso que sobra en la página. Gemela de «Errores en el navegador», y como
 * ella solo se monta para administradores.
 */

import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn, formatDateTime, formatNumber } from "@/lib/utils";
import { useCspViolaciones } from "../../_hooks/use-csp-violaciones";

export function CspViolacionesCard() {
  const { data, isLoading, error, refetch } = useCspViolaciones();

  const filas = data?.items ?? [];
  const dias = data?.dias ?? 30;

  return (
    <Panel>
      <PanelTitle
        title="Bloqueos de la política CSP"
        hint={`Recursos que el navegador bloqueó en los últimos ${dias} días, por directiva y origen`}
      />
      {isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los bloqueos de la política CSP"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún bloqueo registrado"
          hint="Cuando la política bloquee un recurso en el navegador de alguien, aparecerá aquí con su origen."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-tf-body">
            <caption className="sr-only">Violaciones de la política CSP, agrupadas</caption>
            <thead className="border-y border-divider">
              <tr>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Directiva
                </th>
                <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                  Origen
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
                <tr
                  key={`${fila.directiva}|${fila.origen}`}
                  className="border-b border-divider last:border-0"
                >
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-tf-meta">
                    {fila.directiva}
                  </td>
                  <td className="max-w-0 px-3 py-2">
                    <Pista
                      contenido={
                        fila.documento_ejemplo ? `Visto en ${fila.documento_ejemplo}` : undefined
                      }
                    >
                      <span className="block truncate font-mono text-tf-meta text-muted-foreground">
                        {fila.origen}
                      </span>
                    </Pista>
                    {/* La pista no es focusable: el documento también va en el texto. */}
                    {fila.documento_ejemplo && (
                      <span className="sr-only">Visto en {fila.documento_ejemplo}</span>
                    )}
                  </td>
                  <td className="tf-tnum px-3 py-2 text-right font-medium">
                    {formatNumber(fila.veces)}
                  </td>
                  <td className="tf-tnum whitespace-nowrap px-3 py-2 text-tf-meta text-muted-foreground">
                    {formatDateTime(fila.ultima_vez)}
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
