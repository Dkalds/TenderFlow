"use client";

/**
 * Inspector de Cartera: el contrato seleccionado, en el mismo plano que la
 * tabla.
 *
 * La tabla contesta «qué tengo y qué se me acaba»; lo que faltaba era el resto
 * del contrato —cuándo empezó, cuánto se adjudicó, qué le ha ido pasando— sin
 * salir de la pantalla. Es el reparto que ya usan el Radar y la Agenda: lista a
 * la izquierda, detalle a la derecha, sin navegar.
 *
 * Decisión escrita, la misma de la Agenda: **el inspector no baja de `xl`**. No
 * se pierde ninguna acción por debajo de ese ancho —«Preparar renovación» y el
 * enlace a la oportunidad viven en la fila, a todos los anchos—; lo que no cabe
 * es la lectura larga, y encajarla en 375 px pide una hoja a pantalla completa,
 * que es trabajo aparte. Por eso el botón que selecciona la fila tampoco existe
 * por debajo de `xl`: un control que no hace nada visible es peor que su
 * ausencia.
 */
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { PanelEmpty, SectionTitle } from "@/components/console/panel";
import { fechaCorta } from "@/lib/adjudicacion-prevista";
import type { ContratoCartera } from "@/lib/cartera";
import { plazoRestante, urgenciaCartera } from "@/lib/cartera";
import { cn, EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { PrepararRenovacion } from "../preparar-renovacion";
import { CarteraEventos } from "./cartera-eventos";
import { OrigenFin } from "./origen-fin";

export function CarteraInspector({ contrato }: { contrato: ContratoCartera | null }) {
  return (
    <aside
      aria-label="Detalle del contrato seleccionado"
      className="hidden min-w-0 self-start rounded-xl border border-border/60 bg-card p-4 xl:sticky xl:top-0 xl:block"
    >
      {!contrato ? (
        <PanelEmpty size="sm" hint="Selecciona un contrato para ver su detalle y su cronología." />
      ) : (
        <div className="space-y-4">
          <div>
            <h3 className="text-tf-body font-semibold">
              {contrato.titulo ?? contrato.licitacion_id}
            </h3>
            <p className="mt-1 truncate text-tf-micro text-muted-foreground">
              {contrato.organo_contratacion ?? "Órgano sin publicar"}
              {contrato.tecnologia ? ` · ${contrato.tecnologia}` : null}
            </p>
          </div>

          <dl className="space-y-1.5 text-tf-meta">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="flex-none text-muted-foreground">Fin efectivo</dt>
              <dd className="flex items-center gap-0.5 text-right">
                <span className="tf-tnum">
                  {contrato.fecha_fin_efectiva ? fechaCorta(contrato.fecha_fin_efectiva) : EMPTY}
                </span>
                <OrigenFin origen={contrato.fecha_fin_origen} />
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted-foreground">Plazo</dt>
              <dd
                className={cn(
                  "text-right",
                  urgenciaCartera(contrato) === "vencido" || urgenciaCartera(contrato) === "pronto"
                    ? "font-medium text-warning"
                    : null,
                )}
              >
                {plazoRestante(contrato)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted-foreground">Inicio</dt>
              <dd className="tf-tnum text-right">
                {contrato.fecha_inicio ? fechaCorta(contrato.fecha_inicio) : EMPTY}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted-foreground">Adjudicado</dt>
              <dd className="tf-tnum text-right">
                {contrato.importe_adjudicado != null
                  ? formatCompactCurrency(contrato.importe_adjudicado)
                  : EMPTY}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted-foreground">Prórrogas</dt>
              <dd className="tf-tnum text-right">
                {formatNumber(contrato.prorrogas_aplicadas)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="flex-none text-muted-foreground">Relicitación</dt>
              <dd className="text-right">
                {contrato.relicitacion_desde && contrato.relicitacion_hasta ? (
                  <>
                    <span className="tf-tnum">
                      {fechaCorta(contrato.relicitacion_desde)} –{" "}
                      {fechaCorta(contrato.relicitacion_hasta)}
                    </span>
                    {/* La ventana es una estimación de dominio (6 a 3 meses
                        antes del fin) y se dice cada vez que se enseña: sin el
                        matiz se lee como una fecha publicada. */}
                    <span className="block text-tf-micro text-muted-foreground">
                      Estimación: 6 a 3 meses antes del fin
                    </span>
                  </>
                ) : (
                  <span className="text-muted-foreground">Sin fecha de fin</span>
                )}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="flex-none text-muted-foreground">Expediente</dt>
              <dd className="min-w-0 text-right">
                {contrato.url ? (
                  // Al expediente en PLACSP, nunca al documento: los enlaces
                  // directos a pliegos llevan tokens rotativos y caducan.
                  <a
                    href={contrato.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 truncate font-mono text-tf-micro hover:underline"
                  >
                    {contrato.licitacion_id}
                    <ExternalLink className="h-3 w-3 flex-none" aria-hidden="true" />
                  </a>
                ) : (
                  <span className="truncate font-mono text-tf-micro">{contrato.licitacion_id}</span>
                )}
              </dd>
            </div>
          </dl>

          <div className="border-t border-border/50 pt-3">
            <SectionTitle>Cronología del contrato</SectionTitle>
            {/* `key` por contrato: al cambiar de fila el bloque se remonta con
                su propio estado de carga en vez de enseñar los eventos del
                anterior mientras llegan los suyos. */}
            <CarteraEventos key={contrato.id} carteraId={contrato.id} />
          </div>

          <div className="border-t border-border/50 pt-3">
            <SectionTitle>Renovación</SectionTitle>
            {contrato.renovacion_pursuit_id ? (
              <Link
                href={`/oportunidades/${contrato.renovacion_pursuit_id}`}
                className="text-tf-meta font-medium text-primary hover:underline"
              >
                Abrir la oportunidad de renovación
              </Link>
            ) : (
              <>
                <p className="text-tf-meta text-muted-foreground">
                  Este contrato todavía no tiene oportunidad de relicitación.
                </p>
                <PrepararRenovacion
                  carteraId={contrato.id}
                  licitacionVigente={contrato.licitacion_id}
                  titulo={contrato.titulo ?? contrato.licitacion_id}
                />
              </>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
