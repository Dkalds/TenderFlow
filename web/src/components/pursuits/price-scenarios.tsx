"use client";

import { useParams } from "next/navigation";
import { Check, ShieldAlert } from "lucide-react";
import { Panel, PanelEmpty, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TarifasPresupuesto } from "@/components/pliego/tarifas-presupuesto";
import { usePriceScenarios } from "@/hooks/use-price-scenarios";
import { usePursuit } from "@/hooks/use-pursuits";
import { formatCurrency, formatPercent } from "@/lib/utils";

const names = {
  defensivo: "Defensivo",
  central: "Central",
  competitivo: "Competitivo",
} as const;

/**
 * Los criterios con los que `services/ml/pricing_scenarios.py` elige las
 * adjudicaciones comparables (`cohort`), dichos como se dirían en una reunión.
 * Uno que no esté aquí se enseña tal cual llega: mejor la clave que nada.
 */
const CRITERIO_COHORTE: Record<string, string> = {
  organo: "mismo órgano",
  cpv4: "mismo CPV (4 dígitos)",
  importe: "importe parecido",
  competencia: "competencia parecida",
};

// Formato compartido: ver `no-restricted-syntax` en eslint.config.mjs.
const eur = (value: number): string => formatCurrency(value);

const percent = (value: number): string => formatPercent(value * 100);

/**
 * Escenarios de precio de la oportunidad abierta.
 *
 * Si la oportunidad se abrió **por lote** (S3.1), el precio que hay que
 * proponer es el de ese lote: el panel pide su escenario, no el del expediente
 * completo. `loteId` explícito manda; cuando no se pasa, el lote sale del
 * pursuit de la ruta, que ya está en la caché de react-query porque la página
 * no llega a renderizar esta pestaña hasta tenerlo (misma clave: no hay segunda
 * llamada).
 *
 * `loteId === null` es distinto de `undefined`: null significa «el expediente
 * entero, y lo sé», y no dispara la resolución por ruta.
 *
 * Con `onUsarPrecio`, cada escenario ofrece fijarse como oferta prevista. La
 * pestaña calculaba tres precios y el único sitio donde anotar uno era el
 * formulario completo de otra pestaña, a mano y sin copiar.
 */
export function PriceScenariosPanel({
  licitacionId,
  loteId,
  loteNumero,
  ofertaPrevista,
  onUsarPrecio,
  usando = false,
}: {
  licitacionId: string;
  loteId?: number | null;
  loteNumero?: string | null;
  /** La oferta prevista de la oportunidad, para marcar el escenario que ya lo es. */
  ofertaPrevista?: number | null;
  onUsarPrecio?: (precio: number) => void;
  usando?: boolean;
}) {
  const params = useParams<{ id: string }>();
  const pursuitId = params?.id ?? null;
  const explicito = loteId !== undefined;
  const pursuit = usePursuit(explicito ? null : pursuitId);
  const lote = explicito ? (loteId ?? null) : (pursuit.data?.lote_id ?? null);
  const numero = explicito ? (loteNumero ?? null) : (pursuit.data?.lote_numero ?? null);
  // Mientras no se sepa si hay lote no se pide nada: pedir el del expediente y
  // sustituirlo por el del lote es enseñar un precio equivocado y corregirlo a
  // la vista del usuario.
  const resolviendo = !explicito && pursuitId !== null && pursuit.isPending;
  const query = usePriceScenarios(licitacionId, lote, { enabled: !resolviendo });

  if (resolviendo || query.isLoading) {
    return <Skeleton className="h-56 w-full rounded-xl" />;
  }
  if (query.error) {
    return (
      <Panel>
        <SectionTitle>Escenarios de precio</SectionTitle>
        <PanelEmpty message="Los escenarios de precio no están disponibles para esta licitación." />
      </Panel>
    );
  }

  const data = query.data;
  if (!data) return null;
  // El coste y la fuente son los mismos en los tres escenarios (sólo cambia el
  // precio): se dicen una vez bajo la rejilla.
  const margen = data.scenarios?.find((s) => s.margen_implicito)?.margen_implicito ?? null;
  const qualityVariant =
    data.sample_quality === "robusta"
      ? "success"
      : data.sample_quality === "indicativa"
        ? "warning"
        : "secondary";
  const criterios = (data.cohort ?? []).map((clave) => CRITERIO_COHORTE[clave] ?? clave);

  return (
    <Panel>
      <SectionTitle
        aside={
          <span className="flex flex-wrap items-center gap-1.5">
            {lote != null && <Badge variant="outline">Lote {numero ?? lote}</Badge>}
            <Badge variant={qualityVariant}>Muestra {data.sample_quality}</Badge>
          </span>
        }
      >
        Escenarios de precio
      </SectionTitle>
      <p className="text-muted-foreground mb-3 text-tf-meta leading-relaxed">
        {lote != null
          ? `Cuantiles de bajas observadas, sobre el presupuesto del lote ${numero ?? lote}.`
          : "Cuantiles de bajas observadas en adjudicaciones comparables."}
      </p>

      <div className="space-y-3.5">
        {/* El lote se abrió, pero el pliego ya no lo publica: el `lote_id` que
            resuelve el backend viene NULL y sólo sobrevive su número (v110).
            Los escenarios son entonces los del expediente, y decirlo es más
            barato que dejar que alguien fije un precio creyendo otra cosa. */}
        {lote == null && numero != null && (
          <p className="border-border/60 text-muted-foreground rounded-lg border border-dashed p-3 text-tf-meta">
            El lote {numero} ya no figura publicado; estos escenarios son del expediente completo.
          </p>
        )}
        {data.scenarios?.length ? (
          <div className="grid gap-3 md:grid-cols-3">
            {data.scenarios.map((scenario) => {
              // En euros enteros: es lo que se ve en la tarjeta, y una oferta
              // prevista con céntimos de un cuantil sería precisión inventada.
              const precio = Math.round(scenario.price_eur);
              const esLaPrevista = ofertaPrevista != null && Math.abs(ofertaPrevista - precio) < 1;
              return (
                <div key={scenario.name} className="border-border/60 bg-background/40 rounded-lg border p-3.5">
                  <p className="text-muted-foreground font-mono text-tf-micro font-semibold tracking-wider uppercase">
                    {names[scenario.name]}
                  </p>
                  <p className="tf-tnum mt-1.5 font-mono text-tf-title font-semibold">{eur(scenario.price_eur)}</p>
                  <p className="text-primary mt-1 text-tf-meta font-medium">Baja {percent(scenario.discount)}</p>
                  {/* F2.4 — sólo cuando el pliego publica tarifas y horas; el
                      backend lo calcula y declara la fuente. */}
                  {scenario.margen_implicito && (
                    <p className="mt-2 text-tf-meta">
                      Margen techo{" "}
                      <span className="tf-tnum font-semibold">{eur(scenario.margen_implicito.margen_eur)}</span>
                      {scenario.margen_implicito.margen_pct != null && (
                        <span className="text-muted-foreground">
                          {" "}
                          ({percent(scenario.margen_implicito.margen_pct)})
                        </span>
                      )}
                    </p>
                  )}
                  <p className="text-muted-foreground mt-1.5 text-tf-micro leading-relaxed">{scenario.basis}</p>
                  {onUsarPrecio ? (
                    esLaPrevista ? (
                      <p className="text-success mt-2.5 inline-flex items-center gap-1 text-tf-micro font-semibold">
                        <Check className="h-3 w-3" aria-hidden="true" />
                        Es la oferta prevista
                      </p>
                    ) : (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-2.5"
                        disabled={usando}
                        aria-label={`Usar el escenario ${names[scenario.name].toLowerCase()}, ${eur(precio)}, como oferta prevista`}
                        onClick={() => onUsarPrecio(precio)}
                      >
                        Usar como oferta prevista
                      </Button>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <PanelEmpty message="No hay comparables suficientes para proponer escenarios." />
        )}
        {margen && (
          <p className="text-muted-foreground text-tf-micro leading-relaxed">
            Coste estimado {eur(margen.coste_estimado_eur)} con {margen.perfiles} perfil
            {margen.perfiles === 1 ? "" : "es"}. {margen.fuente}
          </p>
        )}
        {lote == null && <TarifasPresupuesto licitacionId={licitacionId} />}
        <div className="text-muted-foreground flex flex-wrap gap-x-5 gap-y-1 text-tf-micro">
          <span>Muestra de {data.distribution?.n ?? 0} adjudicaciones</span>
          <span>
            {criterios.length ? `Comparables por: ${criterios.join(" · ")}` : "Sin cohorte comparable"}
          </span>
        </div>
        <div className="border-warning/30 bg-warning/10 text-warning flex gap-2 rounded-lg border p-3 text-tf-micro leading-relaxed">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p>{data.disclaimer}</p>
            {!data.win_probability_gate?.available && (
              <p className="mt-1 font-medium">
                Todavía no calculamos la probabilidad de ganar: hace falta un histórico de resultados
                propios y comprobar que acierta antes de publicarla.
              </p>
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}
