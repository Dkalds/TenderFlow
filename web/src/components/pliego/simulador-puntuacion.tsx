"use client";

import * as React from "react";
import { Calculator } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { usePrediccionBaja } from "@/hooks/use-prediccion-baja";
import { type SimulacionPrecio, useSimuladorPrecio } from "@/hooks/use-simulador-precio";
import { registrarEvento } from "@/lib/analytics";
import { formatNumber, formatPercent } from "@/lib/utils";

/**
 * F2.2 — simulador de puntuación de la oferta.
 *
 * Dos lecturas de la misma ruta: la tabla de escenarios de referencia (la que
 * el backend simula sin parámetros) y, cuando el usuario escribe su baja, la
 * simulación de **esa** baja contra la del rival. Separadas porque el hueco
 * que calcula la API es el de la mejor baja simulada: con los cinco escenarios
 * dentro, compararía siempre el 25 % con el rival, que no es lo que nadie está
 * considerando.
 *
 * Nada se calcula aquí. Puntos, temeridad y hueco vienen de la API; sin
 * fórmula extraída la pantalla dice por qué y no enseña cifras (ADR-014).
 */

const FORMULAS: Record<string, string> = {
  proporcional_inversa: "Proporcional inversa",
  lineal_por_tramos: "Lineal por tramos",
  con_umbral_temeridad: "Con umbral de temeridad",
  otra: "Otra fórmula",
};

/** Un texto por motivo: «no disponible» a secas no dice qué hacer. */
export const MOTIVOS_SIN_CALCULO: Record<NonNullable<SimulacionPrecio["sin_calculo"]>, string> = {
  sin_formula:
    "Fórmula no encontrada en el pliego. Sin ella el simulador no calcula: revisa el criterio de precio en el pliego.",
  formula_no_calculable:
    "El pliego publica una fórmula de precio que el simulador no sabe calcular.",
  sin_puntos_de_precio:
    "El pliego no dice cuántos puntos reparte el precio y no consta su peso: sin ese máximo no hay puntos que simular.",
};

type FormulaTelemetria =
  | "proporcional_inversa"
  | "lineal_por_tramos"
  | "con_umbral_temeridad"
  | "otra"
  | "sin_formula";

function formulaParaTelemetria(tipo: string | null | undefined): FormulaTelemetria {
  if (!tipo) return "sin_formula";
  return tipo in FORMULAS ? (tipo as FormulaTelemetria) : "otra";
}

/** «12», «12,5» o «12.5» → 0.125. Fuera de 0–100 o ilegible → `null`. */
export function parsearBajaPct(texto: string): number | null {
  const limpio = texto.trim().replace("%", "").replace(",", ".");
  if (limpio === "") return null;
  const n = Number(limpio);
  if (!Number.isFinite(n) || n < 0 || n > 100) return null;
  return Math.round(n * 100) / 10_000;
}

const pctDe = (fraccion: number) => formatPercent(fraccion * 100);
/** Los puntos vienen redondeados a dos decimales por la API. */
const puntos = (n: number) => formatNumber(n);

function Hueco({ hueco }: { hueco: number }) {
  if (hueco === 0) return <>Empatas en puntos de precio con el rival.</>;
  if (hueco > 0) return <>Sacas {puntos(hueco)} puntos de precio al rival.</>;
  return (
    <>
      Te faltan <strong>{puntos(-hueco)} puntos</strong> de precio frente al rival: habría que
      compensarlos en juicio de valor.
    </>
  );
}

export function SimuladorPuntuacion({ licitacionId }: { licitacionId: string }) {
  const referencia = useSimuladorPrecio(licitacionId);
  const { data: prediccion } = usePrediccionBaja(licitacionId);
  const [propiaTexto, setPropiaTexto] = React.useState("");
  const [rivalTexto, setRivalTexto] = React.useState("");
  const [enviada, setEnviada] = React.useState<{ propia: number; rival: number | null } | null>(
    null,
  );
  const idPropia = React.useId();
  const idRival = React.useId();
  const idError = React.useId();

  const propia = parsearBajaPct(propiaTexto);
  const rivalValida = rivalTexto.trim() === "" || parsearBajaPct(rivalTexto) != null;
  const errorForm = propiaTexto.trim() !== "" && propia == null
    ? "Tu baja tiene que ser un porcentaje entre 0 y 100."
    : !rivalValida
      ? "La baja del rival tiene que ser un porcentaje entre 0 y 100."
      : null;

  const propio = useSimuladorPrecio(
    enviada ? licitacionId : null,
    enviada ? [enviada.propia] : [],
    enviada?.rival ?? null,
  );

  // Telemetría una vez por simulación con respuesta, no por pulsación.
  const emitida = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!enviada || !propio.data || propio.isPlaceholderData) return;
    const clave = `${enviada.propia}|${enviada.rival}`;
    if (emitida.current === clave) return;
    emitida.current = clave;
    registrarEvento("simulador_usado", {
      formula_tipo: formulaParaTelemetria(propio.data.formula_tipo),
    });
  }, [enviada, propio.data, propio.isPlaceholderData]);

  const p90 = prediccion?.baja_real == null ? (prediccion?.p90 ?? null) : null;
  const data = referencia.data;

  const simular = (event: React.FormEvent) => {
    event.preventDefault();
    if (propia == null || errorForm) return;
    setEnviada({ propia, rival: parsearBajaPct(rivalTexto) });
  };

  return (
    <section aria-labelledby={`${idPropia}-titulo`} className="space-y-3">
      <div className="flex items-center gap-2">
        <Calculator className="h-4 w-4 text-primary" aria-hidden="true" />
        <h3 id={`${idPropia}-titulo`} className="text-sm font-medium text-muted-foreground">
          Simulador de puntuación del precio
        </h3>
      </div>

      {referencia.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : referencia.error ? (
        <p role="alert" className="text-sm text-destructive">
          No se pudo consultar el simulador. {(referencia.error as Error).message}
        </p>
      ) : !data ? null : data.sin_calculo ? (
        <p className="rounded-lg border border-dashed border-border/70 bg-muted/25 p-3 text-sm text-muted-foreground">
          {MOTIVOS_SIN_CALCULO[data.sin_calculo]}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            {data.formula_tipo && (
              <Badge variant="secondary">{FORMULAS[data.formula_tipo] ?? data.formula_tipo}</Badge>
            )}
            {data.puntos_precio != null && (
              <span>
                El precio reparte {puntos(data.puntos_precio)} puntos
                {data.puntos_precio_origen === "pliego"
                  ? " (leídos del pliego)"
                  : data.puntos_precio_origen === "peso_precio"
                    ? " (inferidos del peso del precio: el pliego no publica los puntos)"
                    : ""}
                .
              </span>
            )}
          </div>

          <table className="w-full text-sm">
            <caption className="sr-only">Puntos de precio por baja de referencia</caption>
            <thead>
              <tr className="border-b border-border/60 text-left text-xs text-muted-foreground">
                <th scope="col" className="py-1.5 font-medium">Baja</th>
                <th scope="col" className="py-1.5 font-medium">Puntos de precio</th>
                <th scope="col" className="py-1.5 font-medium">
                  <span className="sr-only">Temeridad</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(data.escenarios ?? []).map((escenario) => (
                <tr key={escenario.baja} className="border-b border-border/40 last:border-b-0">
                  <td className="tf-tnum py-1.5">{pctDe(escenario.baja)}</td>
                  <td className="tf-tnum py-1.5 font-medium">
                    {puntos(escenario.puntos)}
                    {data.puntos_precio != null && (
                      <span className="text-muted-foreground"> / {puntos(data.puntos_precio)}</span>
                    )}
                  </td>
                  <td className="py-1.5 text-right">
                    {escenario.temeraria && <Badge variant="warning">Temeraria</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <form onSubmit={simular} className="space-y-2 rounded-lg border border-border/60 p-3" noValidate>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label htmlFor={idPropia} className="text-xs font-medium">Tu baja (%)</label>
                <Input
                  id={idPropia}
                  inputMode="decimal"
                  placeholder="12"
                  value={propiaTexto}
                  onChange={(e) => setPropiaTexto(e.target.value)}
                  aria-invalid={propiaTexto.trim() !== "" && propia == null}
                  aria-describedby={errorForm ? idError : undefined}
                />
              </div>
              <div className="space-y-1">
                <label htmlFor={idRival} className="text-xs font-medium">Baja del rival (%)</label>
                <Input
                  id={idRival}
                  inputMode="decimal"
                  placeholder="opcional"
                  value={rivalTexto}
                  onChange={(e) => setRivalTexto(e.target.value)}
                  aria-invalid={!rivalValida}
                  aria-describedby={errorForm ? idError : undefined}
                />
              </div>
            </div>
            {p90 != null && (
              <button
                type="button"
                className="text-xs font-medium text-primary hover:underline"
                onClick={() => setRivalTexto(String(Math.round(p90 * 1000) / 10).replace(".", ","))}
              >
                Usar como rival el p90 de la baja esperada ({pctDe(p90)})
              </button>
            )}
            {errorForm && (
              <p id={idError} role="alert" className="text-xs text-destructive">{errorForm}</p>
            )}
            <Button type="submit" size="sm" variant="outline" disabled={propia == null || Boolean(errorForm)}>
              Simular
            </Button>
          </form>

          {enviada && propio.data && !propio.data.sin_calculo && (
            <p aria-live="polite" className="text-sm leading-relaxed">
              {propio.data.escenarios?.map((e) => (
                <span key={e.baja}>
                  Con una baja del {pctDe(e.baja)} obtienes <strong>{puntos(e.puntos)}</strong>
                  {propio.data.puntos_precio != null && ` de ${puntos(propio.data.puntos_precio)}`}{" "}
                  puntos de precio.{e.temeraria && " Cae en temeridad: habría que justificarla."}{" "}
                </span>
              ))}
              {propio.data.hueco_vs_referencia != null && (
                <Hueco hueco={propio.data.hueco_vs_referencia} />
              )}
            </p>
          )}
        </>
      )}
    </section>
  );
}
