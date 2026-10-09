"use client";

/**
 * Las secciones del perfil que no son cifras: dónde gana, quién le compra y
 * cómo ha ido contra ti.
 *
 * Las tres pintan lo que el backend ya calculó —`por_ccaa` y
 * `organos_principales` del perfil, y la lista de cruces de «Contra mí»—; aquí
 * solo se decide el dibujo.
 */

import { EnlaceIr, PanelError, SectionTitle } from "@/components/console/panel";
import { RESULTADO_BATALLA, useBatallasContraMi } from "@/components/competitors/company-contra-mi";
import type { CompanyBreakdown } from "@/components/competitors/company-profile-types";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api-types";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatNumber, formatPercent } from "@/lib/utils";

import { buildCasillas } from "../_hooks/casillas-ccaa";
import { Muestra } from "./dibujos";

/* ── Dónde gana ─────────────────────────────────────────────────────── */

/** Clase de cada paso de intensidad; el más alto invierte el texto. */
const PASO_CASILLA = [
  "border border-border/60 text-muted-foreground",
  "bg-primary/10",
  "bg-primary/20",
  "bg-primary/35",
  "bg-primary/50",
  "bg-primary/90 text-primary-foreground",
];

// Las clases de posición van escritas enteras: Tailwind no ve una clase que se
// compone en ejecución.
const COLUMNA = ["", "col-start-1", "col-start-2", "col-start-3", "col-start-4", "col-start-5", "col-start-6", "col-start-7"];
const FILA = ["", "row-start-1", "row-start-2", "row-start-3", "row-start-4", "row-start-5"];

/** Cuántas comunidades se nombran en el pie del mapa. */
const CCAA_EN_PIE = 3;

export function DondeGana({
  porCcaa,
  territorios,
}: {
  porCcaa: CompanyBreakdown[];
  /** Cuántos territorios cuenta la API para la empresa en el ámbito. */
  territorios: number;
}) {
  const { casillas, sinCasilla } = buildCasillas(porCcaa);
  const conDato = casillas
    .flatMap((c) => (c.pct != null ? [{ ...c, pct: c.pct }] : []))
    .sort((a, b) => b.pct - a.pct);
  return (
    <section>
      <SectionTitle as="h3" hint={territorios > 0 ? `${formatNumber(territorios)} territorios` : undefined}>
        Dónde gana
      </SectionTitle>
      {porCcaa.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">Sin adjudicaciones con comunidad autónoma en el ámbito actual.</p>
      ) : (
        <>
          <div
            role="img"
            aria-label={`Peso de cada comunidad en su importe: ${conDato
              .map((c) => `${c.nombre} ${formatPercent(c.pct, 0)}`)
              .join(", ")}`}
            className="grid w-fit grid-cols-[repeat(7,1.625rem)] grid-rows-[repeat(5,1.625rem)] gap-[3px]"
          >
            {casillas.map((casilla) => (
              <Pista
                key={casilla.codigo}
                contenido={
                  casilla.pct != null
                    ? `${casilla.nombre}: ${formatPercent(casilla.pct)} de su importe · ${formatNumber(casilla.contratos)} adjudicaciones`
                    : `${casilla.nombre}: sin adjudicaciones`
                }
              >
                <span
                  className={cn(
                    "grid place-items-center rounded-sm text-tf-micro font-medium",
                    COLUMNA[casilla.columna],
                    FILA[casilla.fila],
                    PASO_CASILLA[casilla.paso],
                  )}
                >
                  {casilla.codigo}
                </span>
              </Pista>
            ))}
          </div>
          <p className="mt-2 text-tf-meta text-muted-foreground">
            {conDato
              .slice(0, CCAA_EN_PIE)
              .map((c) => `${c.nombre} ${formatPercent(c.pct, 0)}`)
              .join(" · ")}
            {/* Una comunidad que no encuentra casilla no se pierde: se dice. */}
            {sinCasilla.length > 0 &&
              ` · fuera del mapa: ${sinCasilla.map((s) => `${s.nombre} ${formatPercent(s.pct, 0)}`).join(", ")}`}
          </p>
        </>
      )}
    </section>
  );
}

/* ── Quién le compra ────────────────────────────────────────────────── */

/** Cuántos órganos llevan nombre en la barra; el resto se agrupa. */
const ORGANOS_CON_NOMBRE = 4;

/**
 * El peso de cada órgano en el importe de la empresa, como barra al 100 %.
 *
 * `cuota_empresa_pct` ya es el porcentaje sobre todo lo que gana la empresa en
 * el ámbito, así que «Otros» es lo que falta hasta 100 y no la suma de la cola
 * recibida (la API manda solo sus diez primeros órganos).
 */
export function QuienLeCompra({ organos, totalOrganos }: { organos: CompanyBreakdown[]; totalOrganos: number }) {
  const conNombre = organos.slice(0, ORGANOS_CON_NOMBRE);
  const resto = Math.max(0, 100 - conNombre.reduce((suma, o) => suma + o.cuota_empresa_pct, 0));
  const otros = totalOrganos - conNombre.length;
  // «Otros» va siempre en `chart-8`, nunca en otro índice.
  const tramos = [
    ...conNombre.map((o, i) => ({ nombre: o.label, pct: o.cuota_empresa_pct, color: CHART_SERIES[i] })),
    ...(resto > 0.05
      ? [
          {
            nombre: otros > 0 ? `Otros ${formatNumber(otros)} órganos` : "Otros órganos",
            pct: resto,
            color: CHART_SERIES[7],
          },
        ]
      : []),
  ];

  let x = 0;
  return (
    <section>
      <SectionTitle as="h3" hint="parte de su importe">
        Quién le compra
      </SectionTitle>
      {conNombre.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">Sin órganos identificados en el ámbito actual.</p>
      ) : (
        <>
          <svg
            role="img"
            aria-label={tramos.map((t) => `${t.nombre}: ${formatPercent(t.pct, 0)}`).join(", ")}
            className="h-5 w-full rounded-md"
            viewBox="0 0 100 8"
            preserveAspectRatio="none"
          >
            {tramos.map((t) => {
              const inicio = x;
              x += t.pct;
              return <rect key={t.nombre} x={inicio} y="0" width={Math.max(0, t.pct - 0.4)} height="8" fill={t.color} />;
            })}
          </svg>
          <ol className="mt-2 space-y-1">
            {tramos.map((t) => (
              <li key={t.nombre} className="flex items-center gap-2 text-tf-meta">
                <Muestra color={t.color} />
                <Pista contenido={t.nombre}>
                  <span className="min-w-0 flex-1 truncate font-medium">{t.nombre}</span>
                </Pista>
                <span className="tf-tnum w-9 flex-none text-right font-semibold">{formatPercent(t.pct, 0)}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

/* ── Contra ti ──────────────────────────────────────────────────────── */

type Resultado = Schemas["Batalla"]["resultado"];

/** Lo que se puede afirmar de este rival, primero. */
const ORDEN: Resultado[] = ["ellos_ganaron", "perdimos", "ganamos", "sin_resolver"];

/**
 * Cada resultado como casilla: tinte y borde del color semántico, nunca relleno
 * sólido. El color no va solo: debajo, el recuento de cada uno en texto.
 */
const CASILLA_RESULTADO: Record<Resultado, { casilla: string; texto: string }> = {
  ellos_ganaron: { casilla: "border-destructive/60 bg-destructive/10", texto: "text-destructive" },
  perdimos: { casilla: "border-warning/60 bg-warning/10", texto: "text-warning" },
  ganamos: { casilla: "border-success/60 bg-success/10", texto: "text-success" },
  sin_resolver: { casilla: "border-muted-foreground/40", texto: "text-muted-foreground" },
};

/** Ventana de los cruces: el defecto del backend. */
const MESES_CONTRA_TI = 24;

/**
 * Los expedientes en los que tu equipo presentó oferta y esta empresa aparece
 * adjudicataria, de un vistazo: una casilla por expediente.
 *
 * Vivía en la segunda pestaña de un panel lateral que solo existía en pantallas
 * anchas. El detalle —nuestra baja frente a la ganadora, expediente a
 * expediente— sigue en el análisis completo.
 */
export function ContraTi({
  empresaId,
  empresaIds,
  hrefDetalle,
}: {
  empresaId: number;
  empresaIds: readonly number[];
  hrefDetalle: string;
}) {
  const { data, isPending, error, refetch } = useBatallasContraMi(String(empresaId), MESES_CONTRA_TI, empresaIds);
  const batallas = data?.batallas ?? [];
  const porResultado = ORDEN.map((resultado) => ({
    resultado,
    n: batallas.filter((b) => b.resultado === resultado).length,
  })).filter((r) => r.n > 0);

  return (
    <section>
      <SectionTitle
        as="h3"
        hint={data && data.n > 0 ? `${formatNumber(data.n)} en común en los ${data.ventana}` : undefined}
      >
        Contra ti
      </SectionTitle>
      {isPending ? (
        <Skeleton className="h-12 w-full" />
      ) : error || !data ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar el historial contra este competidor"
          error={error ?? undefined}
          onRetry={() => void refetch()}
        />
      ) : data.n === 0 ? (
        <p className="text-tf-meta text-muted-foreground">
          Tu equipo no presentó oferta en ningún expediente que haya ganado esta empresa.
        </p>
      ) : (
        <>
          <ul aria-label="Expedientes en común" className="flex flex-wrap gap-1">
            {ORDEN.flatMap((resultado) =>
              batallas
                .filter((b) => b.resultado === resultado)
                .map((b) => (
                  <li key={b.licitacion_id}>
                    <Pista contenido={`${RESULTADO_BATALLA[resultado].label}: ${b.titulo ?? b.licitacion_id}`}>
                      <span
                        className={cn("block h-[1.125rem] w-[1.125rem] rounded-sm border", CASILLA_RESULTADO[resultado].casilla)}
                      >
                        <span className="sr-only">
                          {RESULTADO_BATALLA[resultado].label}: {b.titulo ?? b.licitacion_id}
                        </span>
                      </span>
                    </Pista>
                  </li>
                )),
            )}
          </ul>
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-tf-meta font-medium">
            {porResultado.map(({ resultado, n }) => (
              <span key={resultado} className={cn("tf-tnum", CASILLA_RESULTADO[resultado].texto)}>
                {RESULTADO_BATALLA[resultado].label}: {formatNumber(n)}
              </span>
            ))}
          </p>
          {data.sin_nif_propio && (
            <p className="mt-1 text-tf-meta text-muted-foreground">
              Tu organización no ha declarado su NIF: de un cierre perdido solo se sabe que perdiste, no quién ganó.
            </p>
          )}
          <EnlaceIr href={hrefDetalle} className="mt-1.5">
            Ver cada cruce en «Contra mí» del análisis completo
          </EnlaceIr>
        </>
      )}
    </section>
  );
}
