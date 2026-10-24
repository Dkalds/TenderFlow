"use client";

/**
 * Verdad del dato: lo que la auditoría nocturna mide contra sus umbrales
 * calibrados (plazos que faltan, UTE contadas varias veces, importes sin base
 * declarada, fechas que no son fechas…).
 *
 * Hasta ahora solo llegaba por correo cuando algo se salía de rango; aquí se
 * ve también lo que está bien, con su límite al lado. Cada cifra es la que
 * manda la API: la tarjeta no calcula ni rellena nada (ADR-014). Una sección
 * que no se pudo medir lo dice, en vez de enseñar un cero.
 */

import { useQuery } from "@tanstack/react-query";

import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";
import { formatDateTime, formatNumber } from "@/lib/utils";

type Verdad = Schemas["VerdadDominio"];
type Seccion = Schemas["VerdadSeccion"];
type Metrica = Schemas["VerdadMetrica"];

const ESTADO: Record<Seccion["estado"], { texto: string; variant: "success" | "destructive" | "warning" | "neutral" }> =
  {
    ok: { texto: "En rango", variant: "success" },
    violacion: { texto: "Fuera de rango", variant: "destructive" },
    error: { texto: "Sin medir", variant: "warning" },
    sin_datos: { texto: "Sin datos", variant: "neutral" },
  };

function cifra(valor: number | null | undefined, unidad: string): string {
  if (valor == null) return "—";
  const decimales = unidad === "filas" ? 0 : 2;
  const numero = formatNumber(valor, "es-ES", { decimales });
  return unidad === "%" ? `${numero} %` : `${numero} ${unidad}`;
}

function FilaMetrica({ metrica }: { metrica: Metrica }) {
  return (
    <tr className="border-b border-border/40 last:border-b-0">
      <td className="py-1.5 pr-3">
        {metrica.etiqueta}
        {metrica.detalle ? <span className="block text-tf-meta text-muted-foreground">{metrica.detalle}</span> : null}
      </td>
      <td className={`tf-tnum py-1.5 pr-3 text-right font-medium ${metrica.supera ? "text-destructive" : ""}`}>
        {cifra(metrica.valor, metrica.unidad)}
      </td>
      <td className="tf-tnum py-1.5 text-right text-muted-foreground">
        {metrica.limite == null ? "sin límite" : `límite ${cifra(metrica.limite, metrica.unidad)}`}
      </td>
    </tr>
  );
}

export function VerdadDominioCard() {
  const { data, isLoading, error, refetch } = useQuery<Verdad>({
    queryKey: adminKeys.revision.verdad,
    queryFn: () => apiGet("/api/v1/admin/revision/verdad") as Promise<Verdad>,
    // La medición es cara y se renueva cada hora: no se repite al volver a la pestaña.
    staleTime: 15 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });

  const secciones = data?.secciones ?? [];
  const violaciones = data?.violaciones ?? [];
  const sinPermiso = error instanceof ApiError && error.status === 403;

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Verdad del dato"
        hint={data?.medido_en ? `Medido ${formatDateTime(data.medido_en)}` : undefined}
      />
      <p className="mb-3 max-w-prose text-tf-meta text-muted-foreground">
        Defectos conocidos del dato, medidos contra el valor que tenían al calibrarse. Una cifra fuera de rango es
        que algo ha empeorado desde entonces.
      </p>
      {sinPermiso ? (
        <Aviso tone="info">Sólo los administradores pueden ver la auditoría del dato.</Aviso>
      ) : error ? (
        <PanelError variant="inline" title="No se pudo medir el dato" error={error} onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : secciones.length === 0 ? (
        <PanelEmpty size="sm" title="No hay nada que medir" hint="Sin licitaciones ni adjudicaciones todavía." />
      ) : (
        <div className="space-y-4">
          {violaciones.length > 0 && (
            <Aviso tone="warning" title={`${formatNumber(violaciones.length)} avisos fuera de rango`}>
              {/* Las mismas frases que el correo de la auditoría: plegadas, porque
                  la tabla de abajo ya dice qué cifra se salió. */}
              <details>
                <summary className="cursor-pointer text-tf-meta">Ver el texto de los avisos</summary>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-tf-meta">
                  {violaciones.map((v) => (
                    <li key={v}>{v}</li>
                  ))}
                </ul>
              </details>
            </Aviso>
          )}
          <ul className="space-y-4" aria-label="Secciones de la auditoría">
            {secciones.map((s) => (
              <li key={s.clave} className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-tf-body font-medium">{s.titulo}</h3>
                  <Badge variant={ESTADO[s.estado].variant} size="sm">
                    {ESTADO[s.estado].texto}
                  </Badge>
                </div>
                {s.error ? (
                  <p className="text-tf-meta text-muted-foreground">No se pudo medir: {s.error}</p>
                ) : s.metricas && s.metricas.length > 0 ? (
                  <table className="w-full max-w-2xl text-tf-body">
                    <caption className="sr-only">{s.titulo}</caption>
                    <tbody>
                      {s.metricas.map((m) => (
                        <FilaMetrica key={m.etiqueta} metrica={m} />
                      ))}
                    </tbody>
                  </table>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
