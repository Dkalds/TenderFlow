"use client";

/**
 * F3.2 — «Contra mí»: los expedientes en los que nos cruzamos con este
 * competidor y cómo acabó cada uno.
 *
 * El perfil de empresa cuenta lo que esa empresa gana y no sabe nada de
 * nosotros. Esta pestaña cruza las oportunidades **presentadas** del equipo con
 * las adjudicaciones observadas (`GET /competitive/empresas/{key}/contra-mi`) y
 * enseña, por expediente, el resultado que el backend puede afirmar:
 *
 * - `ellos_ganaron` sólo cuando el adjudicatario observado **es** este
 *   competidor.
 * - `perdimos` cuando cerramos perdido y el adjudicatario es otro o no consta:
 *   no se le atribuye a este rival una victoria que quizá fue de un tercero.
 * - `ganamos` y `sin_resolver`, tal cual.
 *
 * Una fila con `contradiccion` es un cierre `lost` cuyo adjudicatario observado
 * es nuestra propia empresa: el backend la deja `sin_resolver` y la pestaña la
 * señala y cuenta aparte (`contradicciones`) para que alguien revise el cierre.
 *
 * Con `sin_nif_propio` el backend avisa de que no sabe cuál es nuestra empresa
 * en el maestro; la pestaña lo dice y manda a declararlo en Equipo, porque sin
 * ese aviso un historial lleno de «perdimos» parecería un rival invencible.
 *
 * Las bajas llegan en tanto por uno y `null` cuando falta un dato: una fila sin
 * nuestro precio lo dice en vez de dejar la celda en blanco.
 */

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Info } from "lucide-react";
import { PanelEmpty, PanelError, PanelLoading } from "@/components/console/panel";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { competitiveKeys } from "@/lib/query-keys";
import { cn, EMPTY, formatCurrency, formatDate, formatPercent, truncate } from "@/lib/utils";

type BatallasContraMi = Schemas["BatallasContraMi"];
type Batalla = Schemas["Batalla"];
type ResultadoBatalla = Batalla["resultado"];

/** Ventanas ofrecidas. El backend admite 1-120 meses; 24 es su defecto. */
const VENTANAS = [12, 24, 36] as const;

export const RESULTADO_BATALLA: Record<ResultadoBatalla, { label: string; className: string }> = {
  ganamos: { label: "Ganamos", className: "bg-[hsl(var(--success)/0.14)] text-[hsl(var(--success))]" },
  ellos_ganaron: { label: "Ganaron ellos", className: "bg-destructive/12 text-destructive" },
  perdimos: { label: "Perdimos", className: "bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]" },
  sin_resolver: { label: "Sin resolver", className: "bg-muted text-muted-foreground" },
};

/** Orden del resumen: lo que se puede afirmar de este rival, primero. */
const ORDEN_RESULTADOS: ResultadoBatalla[] = ["ellos_ganaron", "perdimos", "ganamos", "sin_resolver"];

export function useBatallasContraMi(empresaKey: string, meses: number) {
  const organizationId = useActiveOrganizationId();
  return useQuery<BatallasContraMi>({
    queryKey: competitiveKeys.contraMi(empresaKey, organizationId, meses),
    // Ruta con parámetro de path: va por `fetchWithAuth` con el retorno tipado
    // desde el esquema generado (la regla de `apiGet` para rutas dinámicas).
    queryFn: () => {
      const query = new URLSearchParams({ meses: String(meses) });
      if (organizationId != null) query.set("organization_id", String(organizationId));
      return fetchWithAuth<BatallasContraMi>(
        `/api/v1/competitive/empresas/${encodeURIComponent(empresaKey)}/contra-mi?${query}`,
      );
    },
    enabled: empresaKey.length > 0,
    staleTime: 5 * 60_000,
  });
}

function baja(valor: number | null | undefined): string {
  return valor == null ? EMPTY : formatPercent(valor * 100);
}

export function CompanyContraMi({ empresaKey }: { empresaKey: string }) {
  const [meses, setMeses] = React.useState<number>(24);
  const { data, isLoading, error, refetch } = useBatallasContraMi(empresaKey, meses);

  const conteo = React.useMemo(() => {
    const porResultado: Partial<Record<ResultadoBatalla, number>> = {};
    for (const batalla of data?.batallas ?? []) {
      porResultado[batalla.resultado] = (porResultado[batalla.resultado] ?? 0) + 1;
    }
    return porResultado;
  }, [data]);
  const sinPrecio = (data?.batallas ?? []).filter((batalla) => batalla.nuestra_baja == null).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-[11px] font-semibold tracking-[0.1em] uppercase">Ventana</span>
        <div role="group" aria-label="Ventana hacia atrás" className="flex gap-1">
          {VENTANAS.map((valor) => (
            <button
              key={valor}
              type="button"
              aria-pressed={meses === valor}
              onClick={() => setMeses(valor)}
              className={cn(
                "tf-pressable h-7 rounded-md border px-2.5 text-[12px] font-medium transition-colors",
                meses === valor
                  ? "border-border/70 bg-secondary text-foreground"
                  : "text-muted-foreground hover:text-foreground border-transparent",
              )}
            >
              {valor} meses
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <PanelLoading height={200} />
      ) : error || !data ? (
        <PanelError
          title="No se pudo cargar el historial contra este competidor"
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
          height={200}
        />
      ) : (
        <>
          {data.sin_nif_propio && (
            <p
              role="note"
              className="border-border/60 bg-muted/30 flex gap-2 rounded-lg border px-3 py-2 text-[12px] leading-[1.5]"
            >
              <Info className="text-muted-foreground mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden="true" />
              <span>
                Tu organización no ha declarado su NIF, así que no sabemos cuál es tu empresa entre los
                adjudicatarios: de un cierre perdido sólo se puede afirmar que perdisteis, no quién ganó.{" "}
                <Link href="/equipo" className="font-medium underline-offset-2 hover:underline">
                  Declararlo en Equipo → Organización
                </Link>
              </span>
            </p>
          )}

          {(data.contradicciones ?? 0) > 0 && (
            <p
              role="note"
              className="flex gap-2 rounded-lg border border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.08)] px-3 py-2 text-[12px] leading-[1.5]"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-none text-[hsl(var(--warning))]" aria-hidden="true" />
              <span>
                {data.contradicciones === 1
                  ? "Un expediente cerrado como perdido aparece adjudicado a vuestro NIF."
                  : `${data.contradicciones} expedientes cerrados como perdidos aparecen adjudicados a vuestro NIF.`}{" "}
                No se cuentan como derrota: revisad el cierre de la oportunidad o la adjudicación publicada.
              </span>
            </p>
          )}

          {data.n === 0 ? (
            <PanelEmpty
              message={`Ningún expediente en los ${data.ventana} en el que tu equipo presentara oferta y este competidor aparezca como adjudicatario.`}
            />
          ) : (
            <>
              <p className="text-[12.5px]">
                <span className="font-semibold">{data.n}</span>{" "}
                {data.n === 1 ? "expediente" : "expedientes"} en común en los {data.ventana}
                {ORDEN_RESULTADOS.filter((resultado) => conteo[resultado]).map((resultado) => (
                  <span key={resultado} className="text-muted-foreground">
                    {" · "}
                    {RESULTADO_BATALLA[resultado].label.toLowerCase()}: {conteo[resultado]}
                  </span>
                ))}
                {sinPrecio > 0 && (
                  <span className="text-muted-foreground">
                    {" · "}en {sinPrecio} no registrasteis vuestro precio
                  </span>
                )}
              </p>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12px]">
                  <caption className="sr-only">Expedientes en los que coincidimos con este competidor</caption>
                  <thead className="text-muted-foreground text-[10.5px] uppercase">
                    <tr className="border-border/60 border-b">
                      <th scope="col" className="py-1.5 pr-3 font-medium">Expediente</th>
                      <th scope="col" className="py-1.5 pr-3 font-medium">Resultado</th>
                      <th scope="col" className="py-1.5 pr-3 text-right font-medium">Nuestra baja</th>
                      <th scope="col" className="py-1.5 pr-3 text-right font-medium">Baja ganadora</th>
                      <th scope="col" className="py-1.5 text-right font-medium">Adjudicación</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.batallas?.map((batalla) => (
                      <tr key={batalla.licitacion_id} className="border-border/40 border-b align-top">
                        <td className="py-2 pr-3">
                          <Link
                            href={`/detalle?lic=${encodeURIComponent(batalla.licitacion_id)}`}
                            className="font-medium hover:underline"
                          >
                            {truncate(batalla.titulo ?? batalla.licitacion_id, 80)}
                          </Link>
                          <span className="text-muted-foreground block text-[11px]">
                            {batalla.organo_contratacion ?? EMPTY}
                            {batalla.importe != null && ` · ${formatCurrency(batalla.importe)}`}
                          </span>
                        </td>
                        <td className="py-2 pr-3">
                          <span
                            className={cn(
                              "rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap",
                              RESULTADO_BATALLA[batalla.resultado].className,
                            )}
                          >
                            {RESULTADO_BATALLA[batalla.resultado].label}
                          </span>
                          {batalla.contradiccion && (
                            <span className="mt-1 block text-[10.5px] font-medium text-[hsl(var(--warning))]">
                              Cerrado perdido, adjudicado a vosotros
                            </span>
                          )}
                        </td>
                        <td className="tf-tnum py-2 pr-3 text-right">
                          {batalla.nuestra_baja == null ? (
                            <span className="text-muted-foreground text-[11px]">Sin precio registrado</span>
                          ) : (
                            baja(batalla.nuestra_baja)
                          )}
                        </td>
                        <td className="tf-tnum py-2 pr-3 text-right">{baja(batalla.baja_ganadora)}</td>
                        <td className="py-2 text-right whitespace-nowrap">{formatDate(batalla.fecha)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
