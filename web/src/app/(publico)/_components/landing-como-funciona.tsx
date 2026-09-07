import { CONTENIDO } from "../_content/landing";
import { CapturaProducto } from "./landing-captura";
import { KICKER } from "./landing-piel";
import { MarcoCaptura } from "./marco-captura";

/**
 * Cómo funciona: las tres decisiones, en tres columnas separadas por filete.
 *
 * Eran tarjetas con borde, sombra, un icono dentro de un cuadrado tintado y un
 * numeral en monoespaciada arriba a la derecha: cuatro capas de adorno para
 * tres párrafos.
 *
 * El `id` es el destino del CTA secundario del hero, así que no se renombra sin
 * cambiar también el ancla de `landing-hero.tsx`.
 */
export function ComoFuncionaLanding() {
  return (
    <section id="como-funciona" className="mx-auto w-full max-w-6xl scroll-mt-40 px-6 py-20 sm:scroll-mt-24">
      <p className={KICKER}>{CONTENIDO.pilaresKicker}</p>
      <h2 className="font-display mt-4 max-w-[24ch] text-3xl leading-[1.1] font-semibold tracking-[-0.02em] text-balance md:text-4xl">
        {CONTENIDO.pilaresTitulo}
      </h2>
      <div className="border-border/50 mt-12 grid gap-x-12 gap-y-10 border-t pt-10 md:grid-cols-3">
        {CONTENIDO.pilares.map((pilar) => (
          <article key={pilar.titulo}>
            <h3 className="font-display text-xl font-semibold tracking-[-0.01em]">{pilar.titulo}</h3>
            <p className="text-muted-foreground mt-3 text-base leading-relaxed">{pilar.texto}</p>
          </article>
        ))}
      </div>

      {/* La captura, aquí y no en el hero: enseña cómo se trabaja con lo que
          las tres columnas acaban de describir. Con su nota de datos de
          demostración pegada, que viaja con la figura y no con la página. */}
      <figure className="mt-16">
        <h3 className="font-display text-xl font-semibold tracking-[-0.01em]">{CONTENIDO.capturaTitulo}</h3>
        <p className="text-muted-foreground mt-3 max-w-[62ch] text-base leading-relaxed">{CONTENIDO.capturaTexto}</p>
        <div className="mt-8">
          <MarcoCaptura etiqueta={CONTENIDO.capturaEtiqueta}>
            <CapturaProducto />
          </MarcoCaptura>
        </div>
        <figcaption className="text-muted-foreground mt-3 text-xs">{CONTENIDO.capturaNota}</figcaption>
      </figure>
    </section>
  );
}
