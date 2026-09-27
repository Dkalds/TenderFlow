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
 * Cuando la ficha suma varias identidades del maestro, la pestaña manda el
 * grupo entero (`empresa_ids`), como el perfil y el listado: lo que gana
 * cualquiera de ellas es una victoria de este competidor. Hasta 2026-09-25
 * cruzaba sólo la identidad que abre la ficha. Que cruzó el grupo lo dice
 * `claves`, que declara el backend: la pestaña no lo afirma por su cuenta.
 *
 * Las bajas llegan en tanto por uno y `null` cuando falta un dato: una fila sin
 * nuestro precio lo dice en vez de dejar la celda en blanco.
 */

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Aviso, EnlaceIr, PanelEmpty, PanelError, PanelLoading, ROTULO_DATO, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { competitiveKeys } from "@/lib/query-keys";
import { EMPTY, formatCurrency, formatDate, formatPercent, truncate } from "@/lib/utils";

type BatallasContraMi = Schemas["BatallasContraMi"];
type Batalla = Schemas["Batalla"];
type ResultadoBatalla = Batalla["resultado"];

/** Ventanas ofrecidas. El backend admite 1-120 meses; 24 es su defecto. */
const VENTANAS = [12, 24, 36] as const;

/** Etiqueta y tono de cada resultado: los tintes /10 de la casa, vía `Badge`. */
export const RESULTADO_BATALLA: Record<
  ResultadoBatalla,
  { label: string; variant: "success" | "destructive" | "warning" | "neutral" }
> = {
  ganamos: { label: "Ganamos", variant: "success" },
  ellos_ganaron: { label: "Ganaron ellos", variant: "destructive" },
  perdimos: { label: "Perdimos", variant: "warning" },
  sin_resolver: { label: "Sin resolver", variant: "neutral" },
};

const OPCIONES_VENTANA = VENTANAS.map((valor) => ({ value: String(valor), label: `${valor} meses` }));

/** Orden del resumen: lo que se puede afirmar de este rival, primero. */
const ORDEN_RESULTADOS: ResultadoBatalla[] = ["ellos_ganaron", "perdimos", "ganamos", "sin_resolver"];

export function useBatallasContraMi(empresaKey: string, meses: number, empresaIds: readonly number[] = []) {
  const organizationId = useActiveOrganizationId();
  // Con una sola identidad no hay grupo que mandar: la ruta cruza la del path.
  const grupo = empresaIds.length > 1 ? empresaIds.join(",") : null;
  return useQuery<BatallasContraMi>({
    queryKey: competitiveKeys.contraMi(empresaKey, organizationId, meses, grupo),
    // Ruta con parámetro de path: va por `fetchWithAuth` con el retorno tipado
    // desde el esquema generado (la regla de `apiGet` para rutas dinámicas).
    queryFn: () => {
      const query = new URLSearchParams({ meses: String(meses) });
      if (organizationId != null) query.set("organization_id", String(organizationId));
      if (grupo) query.set("empresa_ids", grupo);
      return fetchWithAuth<BatallasContraMi>(
        `/api/v1/competitive/empresas/${encodeURIComponent(empresaKey)}/contra-mi?${query}`,
      );
    },
    // «Contra mí» es contra la organización activa: sin saber cuál es, la
    // comparación saldría contra la personal, que no ha competido con nadie.
    enabled: empresaKey.length > 0 && organizacionResuelta(organizationId),
    staleTime: 5 * 60_000,
    // El fallo se dice en la pestaña (PanelError): sin toast además.
    meta: META_ERROR_EN_LINEA,
  });
}

function baja(valor: number | null | undefined): string {
  return valor == null ? EMPTY : formatPercent(valor * 100);
}

export function CompanyContraMi({
  empresaKey,
  empresaIds,
}: {
  empresaKey: string;
  /** Todas las identidades que suma la ficha, la de `empresaKey` incluida. */
  empresaIds?: readonly number[];
}) {
  const [meses, setMeses] = React.useState<number>(24);
  const { data, isPending, error, refetch } = useBatallasContraMi(empresaKey, meses, empresaIds);
  const identidades = data?.claves?.length ?? 0;

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
        <span className={ROTULO_DATO} aria-hidden="true">
          Ventana
        </span>
        <Segmented
          aria-label="Ventana hacia atrás"
          value={String(meses)}
          onChange={(valor) => setMeses(Number(valor))}
          options={OPCIONES_VENTANA}
        />
      </div>

      {isPending ? (
        <PanelLoading height={200} />
      ) : error || !data ? (
        <PanelError
          title="No se pudo cargar el historial contra este competidor"
          error={error ?? undefined}
          onRetry={() => void refetch()}
          height={200}
        />
      ) : (
        <>
          {identidades > 1 && (
            <p className="text-tf-meta text-muted-foreground">
              Cruza las {identidades} identidades del maestro que suma esta ficha.
            </p>
          )}

          {data.sin_nif_propio && (
            <Aviso
              tone="info"
              role="note"
              action={<EnlaceIr href="/equipo">Declararlo en Equipo › Organización</EnlaceIr>}
            >
              Tu organización no ha declarado su NIF, así que no sabemos cuál es tu empresa entre los
              adjudicatarios: de un cierre perdido solo se puede afirmar que tu equipo perdió, no quién ganó.
            </Aviso>
          )}

          {(data.contradicciones ?? 0) > 0 && (
            <Aviso tone="warning" role="note">
              {data.contradicciones === 1
                ? "Un expediente cerrado como perdido aparece adjudicado al NIF de tu organización."
                : `${data.contradicciones} expedientes cerrados como perdidos aparecen adjudicados al NIF de tu organización.`}{" "}
              No se cuentan como derrota: revisa el cierre de la oportunidad o la adjudicación publicada.
            </Aviso>
          )}

          {data.n === 0 ? (
            <PanelEmpty
              title={`Ningún expediente en los ${data.ventana}`}
              hint="Tu equipo no presentó oferta en ninguno en el que este competidor aparezca como adjudicatario."
            />
          ) : (
            <>
              <p className="text-tf-body">
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
                    {" · "}en {sinPrecio} tu equipo no registró su precio
                  </span>
                )}
              </p>

              <Table>
                <caption className="sr-only">Expedientes en los que coincidimos con este competidor</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Expediente</TableHead>
                    <TableHead>Resultado</TableHead>
                    <TableHead className="text-right">Nuestra baja</TableHead>
                    <TableHead className="text-right">Baja ganadora</TableHead>
                    <TableHead className="text-right">Adjudicación</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.batallas?.map((batalla) => (
                    <TableRow key={batalla.licitacion_id} className="align-top">
                      <TableCell>
                        <Link
                          href={`/detalle?lic=${encodeURIComponent(batalla.licitacion_id)}`}
                          className="font-medium transition-colors hover:text-primary"
                        >
                          {truncate(batalla.titulo ?? batalla.licitacion_id, 80)}
                        </Link>
                        <span className="block text-tf-meta text-muted-foreground">
                          {batalla.organo_contratacion ?? EMPTY}
                          {batalla.importe != null && ` · ${formatCurrency(batalla.importe)}`}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={RESULTADO_BATALLA[batalla.resultado].variant} size="sm" className="whitespace-nowrap">
                          {RESULTADO_BATALLA[batalla.resultado].label}
                        </Badge>
                        {batalla.contradiccion && (
                          <span className="mt-1 block text-tf-micro font-medium text-warning">
                            Cerrado perdido, adjudicado a tu organización
                          </span>
                        )}
                      </TableCell>
                      <TableCell numeric>
                        {batalla.nuestra_baja == null ? (
                          <span className="text-tf-meta text-muted-foreground">Sin precio registrado</span>
                        ) : (
                          baja(batalla.nuestra_baja)
                        )}
                      </TableCell>
                      <TableCell numeric>{baja(batalla.baja_ganadora)}</TableCell>
                      <TableCell numeric className="whitespace-nowrap">
                        {formatDate(batalla.fecha)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </>
      )}
    </div>
  );
}
