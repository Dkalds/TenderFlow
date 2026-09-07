import Link from "next/link";
import { CONTENIDO } from "../_content/landing";
import { CtaAcceso } from "./landing-cta";
import { CTA_SECUNDARIO, ENTRADA_HERO, KICKER } from "./landing-piel";
import { UltimosPublicados } from "./ultimos-publicados";

/**
 * Portada de la landing.
 *
 * Dos columnas en escritorio: el argumento a la izquierda, el dato a la
 * derecha. No es una retícula decorativa — es la tesis de la página puesta en
 * el espacio: lo que se promete, y al lado la prueba, sin que haya que bajar
 * para encontrarla. En móvil se apilan en ese mismo orden.
 *
 * El texto va alineado a la izquierda. Centrado sobre una imagen a sangre era
 * lo que pedía la composición anterior; con una columna de medida legible,
 * centrar sólo dificulta la lectura.
 *
 * El cambio de fondo de 2026-09 está aquí: donde había una **foto** del
 * producto hay cinco expedientes **reales**, servidos por la API pública (ver
 * `ultimos-publicados.tsx`). Un producto cuyo argumento es la calidad del dato
 * no puede abrir con una captura de datos de demostración; la captura sigue
 * existiendo, pero baja a la sección que explica cómo se trabaja.
 */
export function HeroLanding() {
  return (
    <section className="mx-auto w-full max-w-6xl px-6 pt-14 pb-16 md:pt-20">
      <div className="grid items-start gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <div className="tf-stagger">
          <p className={`${ENTRADA_HERO} ${KICKER}`}>{CONTENIDO.eyebrow}</p>
          <h1
            className={`${ENTRADA_HERO} font-display mt-5 max-w-[16ch] text-4xl leading-[1.02] font-semibold tracking-[-0.02em] text-balance md:text-6xl`}
          >
            {CONTENIDO.h1}
          </h1>
          <p className={`${ENTRADA_HERO} text-muted-foreground mt-6 max-w-[52ch] text-lg leading-relaxed text-pretty`}>
            {CONTENIDO.subtitulo}
          </p>
          {/* Descalificar aquí y no cuatro pantallas más abajo. Va con el
              peso del cuerpo y no en gris de nota: es una afirmación del
              producto, no una letra pequeña, y quien no encaja tiene que
              poder leerla de una pasada y marcharse sin gastar la página. */}
          <p className={`${ENTRADA_HERO} text-foreground/80 mt-4 max-w-[52ch] text-base leading-relaxed`}>
            {CONTENIDO.heroAcotacion}
          </p>
          <div className={`${ENTRADA_HERO} mt-8 flex flex-wrap items-center gap-3`}>
            <CtaAcceso utmContent="hero" />
            <Link href="#como-funciona" className={CTA_SECUNDARIO}>
              {CONTENIDO.ctaSecundario}
            </Link>
          </div>
          <p className={`${ENTRADA_HERO} text-muted-foreground mt-5 max-w-[56ch] text-xs leading-relaxed`}>
            {CONTENIDO.notaFuentes}
          </p>
        </div>

        {/* La prueba, no la promesa: expedientes reales del corpus público,
            con su enlace a la ficha. Es un componente async y la página sigue
            siendo estática con ISR, así que la llamada ocurre al generar. */}
        <div className={ENTRADA_HERO}>
          <UltimosPublicados />
        </div>
      </div>
    </section>
  );
}
