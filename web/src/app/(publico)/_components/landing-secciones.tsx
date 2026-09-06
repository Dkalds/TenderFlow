import { Fragment } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { CONTENIDO } from "../_content/landing";
import type { SeccionLanding } from "../_content/landing-tipos";
import { CtaAcceso } from "./landing-cta";
import { KICKER } from "./landing-piel";

/**
 * Cuerpo en detalle: tres secciones, cada una con su cabecera a la izquierda y
 * el texto a la derecha. El kicker ya no lleva icono ni numeral — el filete y
 * la posición bastan para saber dónde se está.
 *
 * Qué va dentro de cada una lo decide `seccion.icono`, que es una clave y no
 * una posición: reordenar el copy no descoloca ni el diccionario de familias ni
 * el reclamo intermedio.
 */

function CuerpoSeccion({ seccion }: { seccion: SeccionLanding }) {
  return (
    <section className="border-border/40 grid gap-6 border-b py-16 last:border-b-0 md:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] md:gap-14">
      {/* La columna de cabecera acompaña al texto largo con sticky:
          en pantallas cortas el lector nunca pierde de vista en qué
          parte del producto está.

          `top-16` y no `top-24`: el header sticky mide ~58 px, así que
          96 dejaba 38 px de hueco muerto. `z-10` y fondo propio porque
          al desanclarse la columna pasaba por debajo del header
          traslúcido y su título se leía borroso a través del blur. */}
      <div className="bg-background md:sticky md:top-16 md:z-10 md:self-start md:pb-4">
        <p className={KICKER}>{seccion.kicker}</p>
        <h2 className="font-display mt-4 text-2xl leading-[1.15] font-semibold tracking-[-0.02em] text-pretty md:text-3xl">
          {seccion.h2}
        </h2>
      </div>
      <div className="max-w-[66ch]">
        {seccion.parrafos.map((parrafo) => (
          <p key={parrafo} className="text-muted-foreground mb-4 text-base leading-relaxed last:mb-0">
            {parrafo}
          </p>
        ))}
        {/* Los bullets eran filas con un icono de check delante. El
            check no aportaba información —no hay nada que marcar— y
            teñía de folleto una lista de afirmaciones técnicas. */}
        <ul className="border-border/40 mt-8 space-y-3 border-t pt-6">
          {seccion.bullets.map((bullet) => (
            <li key={bullet} className="text-foreground/85 text-base leading-relaxed">
              {bullet}
            </li>
          ))}
        </ul>
        {/* El diccionario de familias vive donde se explica qué entra
            en el corpus, no como franja suelta cargada de keywords. */}
        {seccion.icono === "corpus" && (
          <>
            <p className="text-muted-foreground mt-8 text-sm leading-relaxed">{CONTENIDO.familiasTitulo}</p>
            <ul className="text-foreground/75 mt-4 flex flex-wrap gap-x-4 gap-y-1.5 font-mono text-xs">
              {CONTENIDO.familias.map((familia) => (
                <li key={familia}>{familia}</li>
              ))}
            </ul>
          </>
        )}
        {seccion.enlaces && (
          <div className="mt-8 flex flex-col gap-2.5">
            {seccion.enlaces.map((enlace) => (
              <Link
                key={enlace.href}
                href={enlace.href}
                className="group text-primary inline-flex w-fit items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline"
              >
                {enlace.texto}
                <ArrowRight
                  className="h-3.5 w-3.5 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </Link>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * Único punto de conversión intermedio.
 *
 * El formulario vive al final de la página y el botón del hero salta hasta
 * allí, así que entre una cosa y otra no había dónde actuar: quien terminaba de
 * leer de dónde sale cada número —el momento de más intención— tenía que seguir
 * bajando o irse. Va justo después de esa sección y no repartido por todas: un
 * reclamo cada dos párrafos convierte el argumento en un folleto.
 */
function CtaIntermedio() {
  return (
    <div className="border-border/40 flex flex-wrap items-center justify-between gap-x-8 gap-y-4 border-b py-10">
      <div className="max-w-[46ch]">
        <p className="font-display text-lg font-semibold tracking-[-0.01em]">{CONTENIDO.ctaIntermedioTitulo}</p>
        <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">{CONTENIDO.ctaIntermedioTexto}</p>
      </div>
      <CtaAcceso utmContent="intermedio" />
    </div>
  );
}

export function SeccionesLanding() {
  return (
    <div className="border-border/60 border-t">
      <div className="mx-auto w-full max-w-6xl px-6">
        {CONTENIDO.secciones.map((seccion) => (
          <Fragment key={seccion.h2}>
            <CuerpoSeccion seccion={seccion} />
            {seccion.icono === "scoring" && <CtaIntermedio />}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
