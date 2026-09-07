import { CONTENIDO } from "../_content/landing";
import { KICKER } from "./landing-piel";

/**
 * Preguntas frecuentes.
 *
 * Se pinta del **mismo** array (`CONTENIDO.faq`) del que `page.tsx` construye
 * el `FAQPage` del JSON-LD. Marcar como FAQ preguntas que no están visibles en
 * la página es una infracción explícita de las directrices de Google, y la
 * forma más fácil de cometerla es mantener dos listas: si algún día este bloque
 * filtra o recorta el array, el JSON-LD de la página tiene que filtrar igual.
 */
export function FaqLanding() {
  return (
    <div className="border-border/60 border-t">
      <section className="mx-auto w-full max-w-6xl px-6 py-16">
        <p className={KICKER}>{CONTENIDO.faqKicker}</p>
        <h2 id="faq-titulo" className="font-display mt-4 text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
          {CONTENIDO.faqTitulo}
        </h2>
        <dl aria-labelledby="faq-titulo" className="mt-10 grid gap-x-14 gap-y-8 md:grid-cols-2">
          {CONTENIDO.faq.map((item) => (
            <div key={item.pregunta} className="border-border/50 max-w-[58ch] border-t pt-6">
              <dt className="text-base leading-snug font-semibold">{item.pregunta}</dt>
              <dd className="text-muted-foreground mt-2.5 text-sm leading-relaxed md:text-base">{item.respuesta}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
