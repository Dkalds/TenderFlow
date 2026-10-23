"use client";

/**
 * «Tu baja frente al mercado», junto a los escenarios de precio (C6.5).
 *
 * Los escenarios responden «a qué precio gana el mercado aquí»; esto responde
 * la otra mitad: **«y yo, cuánto bajo»**. `GET /pursuits/mi-baja` existía y no
 * lo pintaba ninguna pantalla, así que al fijar un precio el equipo veía el
 * mercado sin verse a sí mismo.
 *
 * Los segmentos son de toda la organización (CPV de cuatro dígitos y órgano),
 * no de esta oportunidad: la del órgano de esta ficha sube arriba y se marca,
 * pero no se filtra el resto, que es con lo que se lee si una cifra es la
 * costumbre de la casa o una rareza. Los segmentos con menos de cinco ofertas
 * salen con su `n` y marcados: saber que solo hay dos es información (ver
 * `services/pursuit_bajas.py`).
 */

import { Panel, PanelEmpty, PanelError, ROTULO_DATO, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { useMiBaja, type MiBajaSegmento } from "@/hooks/use-mi-baja";
import { cn, formatNumber, formatPercent } from "@/lib/utils";

/** Plegado mínimo para reconocer el órgano de la ficha entre los segmentos. */
function plegar(texto: string | null | undefined): string {
  return (texto ?? "").trim().toLocaleLowerCase("es");
}

function etiquetaSegmento(segmento: MiBajaSegmento): string {
  return segmento.segmento === "cpv4" ? `CPV ${segmento.clave}` : segmento.clave;
}

/** Puntos porcentuales con signo: «+2,3 pp», «−1,0 pp». */
export function formatDelta(delta: number | null | undefined): string {
  if (delta == null) return "—";
  const signo = delta > 0 ? "+" : delta < 0 ? "−" : "";
  return `${signo}${formatNumber(Math.abs(delta), "es-ES", { decimales: 1 })} pp`;
}

/** Primero el órgano de esta ficha; el resto, en el orden del backend (más ofertas antes). */
export function ordenarSegmentos(segmentos: MiBajaSegmento[], organo: string | null | undefined): MiBajaSegmento[] {
  const propio = plegar(organo);
  if (!propio) return segmentos;
  const esDeEsteOrgano = (s: MiBajaSegmento) => s.segmento === "organo" && plegar(s.clave) === propio;
  return [...segmentos.filter(esDeEsteOrgano), ...segmentos.filter((s) => !esDeEsteOrgano(s))];
}

export function MiBajaPanel({ organo }: { organo?: string | null }) {
  const { data, isPending, error, refetch } = useMiBaja();

  if (isPending) return <Skeleton className="h-40 w-full rounded-xl" />;

  if (error) {
    return (
      <Panel>
        <SectionTitle>Tu baja frente al mercado</SectionTitle>
        <PanelError
          variant="inline"
          title="No se pudo calcular tu baja frente al mercado"
          error={error}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  const segmentos = ordenarSegmentos(data.segmentos, organo);
  const propio = plegar(organo);

  return (
    <Panel>
      <SectionTitle
        hint={
          <span className="text-tf-meta text-muted-foreground">
            Sin IVA · {data.ofertas_consideradas}{" "}
            {data.ofertas_consideradas === 1 ? "oferta presentada" : "ofertas presentadas"}
          </span>
        }
      >
        Tu baja frente al mercado
      </SectionTitle>

      {segmentos.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Todavía no hay ofertas tuyas con las que comparar"
          hint="Cuentan las oportunidades con oferta prevista sobre expedientes que declaran su presupuesto sin IVA. Cuando las haya, verás aquí tu baja media por CPV y por órgano junto a la del mercado."
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-tf-meta">
              <thead className="border-b border-border/60">
                <tr>
                  <th scope="col" className={cn("px-3 py-2 text-left", CABECERA_COLUMNA)}>
                    Segmento
                  </th>
                  <th scope="col" className={cn("px-3 py-2 text-right", CABECERA_COLUMNA)}>
                    Tus ofertas
                  </th>
                  <th scope="col" className={cn("px-3 py-2 text-right", CABECERA_COLUMNA)}>
                    Tu baja media
                  </th>
                  <th scope="col" className={cn("px-3 py-2 text-right", CABECERA_COLUMNA)}>
                    Baja ganadora del mercado
                  </th>
                  <th scope="col" className={cn("px-3 py-2 text-right", CABECERA_COLUMNA)}>
                    Diferencia
                  </th>
                </tr>
              </thead>
              <tbody>
                {segmentos.map((s) => {
                  const esEste = s.segmento === "organo" && propio !== "" && plegar(s.clave) === propio;
                  return (
                    <tr
                      key={`${s.segmento}:${s.clave}`}
                      className={cn("border-b border-border/40 last:border-0", esEste && "bg-muted/40")}
                    >
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="line-clamp-2">{etiquetaSegmento(s)}</span>
                          {esEste && (
                            <Badge size="sm" variant="outline">
                              Este órgano
                            </Badge>
                          )}
                          {!s.suficiente && (
                            // El porqué está en la leyenda bajo la tabla.
                            <Badge size="sm" variant="warning">
                              Muestra corta
                            </Badge>
                          )}
                        </span>
                      </th>
                      <td className="tf-tnum px-3 py-2 text-right">{s.n}</td>
                      <td className={cn("tf-tnum px-3 py-2 text-right", !s.suficiente && "text-muted-foreground")}>
                        {formatPercent(s.baja_propia_pct)}
                      </td>
                      <td className="tf-tnum px-3 py-2 text-right">
                        {s.baja_mercado_pct == null ? (
                          <span className="text-muted-foreground">Sin referencia</span>
                        ) : (
                          <>
                            {formatPercent(s.baja_mercado_pct)}
                            <span className="text-muted-foreground block text-tf-micro">
                              {s.contratos_mercado} {s.contratos_mercado === 1 ? "contrato" : "contratos"}
                            </span>
                          </>
                        )}
                      </td>
                      <td className={cn("tf-tnum px-3 py-2 text-right", !s.suficiente && "text-muted-foreground")}>
                        {formatDelta(s.delta_pct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className={cn("mt-2", ROTULO_DATO)}>
            Diferencia positiva: bajas más que quien gana en ese segmento; negativa, menos. Con menos de cinco
            ofertas la media es orientativa.
          </p>
        </>
      )}
    </Panel>
  );
}
