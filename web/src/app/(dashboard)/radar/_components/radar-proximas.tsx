"use client";

import * as React from "react";
import Link from "next/link";
import { CalendarClock } from "lucide-react";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import { estadoLabel } from "@/lib/estados";
import { formatDate, cn } from "@/lib/utils";
import type { RadarProxima, RadarProximasConsola } from "../_hooks/use-radar-proximas";
import { shortEur } from "./radar-shared";

/**
 * Bandeja «Próximas» (T5) — lo que se va a comprar y todavía no se puede ofertar.
 *
 * Universo: `PRE` (anuncio previo) y `CPM` (consulta preliminar) **abiertos**,
 * los dos códigos que normalizó la migración `v91`. El filtro, el orden y los
 * dos denominadores los resuelve `GET /radar/proximas`; aquí no se agrupa, no
 * se ordena y no se completa nada (ADR-014).
 *
 * Por qué no es una `RadarLista` más
 * ----------------------------------
 * Estas filas **no tienen score ni plazo**. El ranking del Radar puntúa
 * expedientes con fecha límite viva, y un anuncio previo no tiene a qué
 * presentarse todavía: pintarle un score obligaría a inventar la dimensión que
 * falta, y una columna «Plazo» vacía en todas las filas sería peor que no
 * tenerla. Tampoco hay triaje (seguir / descartar / abrir oportunidad): las tres
 * acciones sellan el score que el usuario tenía delante, y aquí no hay ninguno.
 * Lo que sí hay es la ficha completa, a un clic.
 *
 * Vacía es el caso normal
 * -----------------------
 * El spike de T5 midió el feed vivo de PLACSP y el anuncio previo es residual;
 * la consulta preliminar ni siquiera es un estado de esa sindicación —entra por
 * las plataformas autonómicas—. Por eso el estado vacío **explica qué es una
 * próxima y por qué hay tan pocas** en vez de decir «no hay resultados», que en
 * una consola de datos se lee como una avería.
 */

/** La fecha prevista, o el hueco declarado. Nunca una estimación. */
function FechaPrevista({ iso }: { iso: string | null | undefined }) {
  if (!iso) {
    return (
      <span className="tf-tnum font-mono text-[11px] font-medium text-muted-foreground/70">
        Sin fecha
      </span>
    );
  }
  return (
    <span className="tf-tnum font-mono text-[11.5px] font-semibold text-foreground">
      {formatDate(iso)}
    </span>
  );
}

function ProximaFila({ item }: { item: RadarProxima }) {
  const codigo = item.estado?.trim() ?? "";
  const meta = [item.id_externo, item.cpv ? `CPV ${item.cpv}` : null, item.ccaa]
    .filter(Boolean)
    .join(" · ");

  return (
    <Link
      href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
      className={cn(
        "flex flex-col gap-2 border-b border-border/40 px-3 py-3 transition-colors duration-110 ease-out",
        "hover:bg-primary/5 focus-visible:bg-primary/5 focus-visible:outline-none",
        "md:grid md:grid-cols-[132px_1fr_176px_108px_120px] md:items-center md:gap-3 md:px-3.5 md:py-2.5",
      )}
    >
      <span className="flex flex-none items-center gap-1.5">
        <span className="rounded-[5px] border border-[hsl(var(--info)/0.26)] bg-[hsl(var(--info)/0.1)] px-1.5 py-0.5 text-[11px] font-medium text-[hsl(var(--info))]">
          {estadoLabel(codigo) || "—"}
        </span>
        {/* La etiqueta dice el nombre; el glosario dice si puedes hacer algo
            con ella. «Consulta preliminar» no le explica a nadie que
            participar no compromete a ofertar. */}
        <GlosarioHint termino={codigo} />
      </span>

      <span className="min-w-0">
        <span className="block line-clamp-2 text-[13px] font-medium leading-[1.35] tracking-[-0.005em] md:line-clamp-1">
          {item.titulo ?? "—"}
        </span>
        <span className="mt-0.5 block truncate font-mono text-[10.5px] leading-[1.3] text-muted-foreground/80">
          {meta}
        </span>
      </span>

      <span className="min-w-0 truncate text-xs leading-[1.35] text-muted-foreground">
        {item.organo_contratacion ?? "—"}
      </span>

      <span className="tf-tnum font-mono text-[13px] font-semibold md:text-right">
        {shortEur(item.importe)}
      </span>

      <span className="flex items-baseline gap-1.5 md:flex-col md:items-end md:gap-0.5">
        <span className="font-mono text-[8.5px] font-semibold uppercase tracking-[0.11em] text-muted-foreground/70">
          Prevista
        </span>
        <FechaPrevista iso={item.fecha_prevista} />
      </span>
    </Link>
  );
}

/**
 * Cabecera de la bandeja: qué se está mirando y con qué cobertura.
 *
 * La proporción «X de Y con fecha prevista» viene entera del backend —los dos
 * números son del universo, no de las filas servidas— y por eso se puede
 * enseñar. Calcularla contando los `fecha_prevista` de la página sería exactamente
 * el anti-patrón de ADR-014: un porcentaje sobre un denominador equivocado.
 */
function ProximasCabecera({ consola }: { consola: RadarProximasConsola }) {
  const { total, conFechaPrevista, truncadas, estados } = consola;

  return (
    <div className="flex-none border-b border-border/60 bg-card/40 px-3 py-2 md:px-3.5">
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        Compras que el órgano ya ha anunciado y que <strong className="font-semibold">todavía
        no han salido a licitación</strong>. Aquí no hay plazo al que presentarse; sirve para
        llegar antes al pliego.
        {/* Los estados que definen la bandeja los declara el servidor y se
            enseñan tal cual llegan: la pantalla no da por hecho cuáles son. Si
            el universo cambia en backend, esta línea cambia con él. */}
        {estados.length > 0 && (
          <>
            {" "}
            Universo:{" "}
            <span className="font-medium text-foreground">
              {estados.map((codigo) => estadoLabel(codigo)).join(" · ")}
            </span>
            , abiertos.
          </>
        )}
      </p>
      {total != null && total > 0 && conFechaPrevista != null && (
        <p className="mt-1 font-mono text-[10.5px] leading-relaxed text-muted-foreground/80">
          <span className="tf-tnum">
            {conFechaPrevista} de {total}
          </span>{" "}
          traen fecha prevista publicada; el resto se listan como «sin fecha». La fecha es la de
          inicio previsto del contrato — la única que la fuente publica antes del pliego, y no se
          estima cuando falta.
          {truncadas > 0 && <> Se muestran las {total - truncadas} primeras.</>}
        </p>
      )}
    </div>
  );
}

/**
 * Estado vacío. No dice «no hay resultados»: dice qué es una próxima y por qué
 * casi nunca hay ninguna, que es la verdad del dato y no un fallo de carga.
 *
 * Sin cifras: el 0,14 % que midió el spike es una medición de una muestra
 * concreta del feed, no un dato vivo de esta pantalla, y pintarlo aquí sería
 * hardcodear analítica que el backend no ha dado (invariante 3 de
 * `web/AGENTS.md`).
 */
function ProximasVacia() {
  return (
    <div className="px-5 py-20 text-center">
      <CalendarClock className="mx-auto mb-3 h-6 w-6 text-muted-foreground/60" aria-hidden="true" />
      <div className="mb-1.5 font-display text-[15px] font-semibold leading-[1.3]">
        Ninguna compra anunciada por ahora
      </div>
      <p className="mx-auto max-w-[460px] text-[13px] leading-[1.55] text-muted-foreground">
        Publicar un anuncio previo es potestativo para el órgano, y la consulta preliminar apenas
        entra por la sindicación de PLACSP — llega sobre todo de las plataformas autonómicas. Que
        esta bandeja esté vacía es lo habitual, no un fallo de carga.
      </p>
    </div>
  );
}

function ProximasError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mx-auto my-10 max-w-[560px] rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
    >
      <div className="mb-2 flex items-center gap-2.5">
        <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
          !
        </span>
        <span className="text-[13.5px] font-semibold text-destructive">
          Error al cargar las próximas
        </span>
      </div>
      <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">{error.message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="tf-pressable h-[30px] rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        ↻ Reintentar
      </button>
    </div>
  );
}

export function RadarProximas({ consola }: { consola: RadarProximasConsola }) {
  const { items, isLoading, error, refetch } = consola;

  return (
    <>
      <ProximasCabecera consola={consola} />
      <div data-slot="radar-proximas" className="min-h-0 flex-1 overflow-y-auto">
        {error ? (
          <ProximasError error={error as Error} onRetry={refetch} />
        ) : isLoading ? (
          <div className="flex flex-col gap-2.5 p-3.5">
            {Array.from({ length: 5 }, (_, index) => (
              <span
                key={index}
                className="tf-shimmer block h-11 rounded-lg"
                style={{ opacity: 1 - index * 0.07 }}
              />
            ))}
          </div>
        ) : items.length === 0 ? (
          <ProximasVacia />
        ) : (
          items.map((item) => <ProximaFila key={item.id_externo} item={item} />)
        )}
      </div>
    </>
  );
}
