import type { Metadata } from "next";
import Link from "next/link";
import {
  OG_IMAGE_COMPARTIDA,
  SITE_NAME,
  SITE_URL,
  TWITTER_COMPARTIDO,
} from "@/lib/site";
import { CONTENIDO } from "./_content/landing";

/**
 * Landing pública — la única página de TenderFlow que un buscador puede
 * indexar, y la primera pantalla de quien llega sin cuenta.
 *
 * Es un Server Component sin una línea de JavaScript de cliente, a propósito:
 * lo que un rastreador lee es el HTML de la respuesta, y todo lo que haya que
 * hidratar para que aparezca el texto es texto que Google puede no ver.
 *
 * `title.absolute` evita la plantilla `%s | TenderFlow` que declara el layout
 * raíz: en la portada duplicaría la marca ("TenderFlow … | TenderFlow") y se
 * comería caracteres del título en el resultado de búsqueda.
 */
export const metadata: Metadata = {
  title: { absolute: CONTENIDO.metaTitle },
  description: CONTENIDO.metaDescription,
  alternates: { canonical: "/" },
  // `OG_IMAGE_COMPARTIDA` no es opcional: declarar `openGraph` aquí reemplaza
  // entero el del layout raíz, y sin esparcirla la portada —la página que la
  // gente comparte— se quedaría sin imagen de preview. Ver `@/lib/site`.
  openGraph: {
    ...OG_IMAGE_COMPARTIDA,
    title: CONTENIDO.metaTitle,
    description: CONTENIDO.metaDescription,
    url: "/",
  },
  twitter: {
    ...TWITTER_COMPARTIDO,
    title: CONTENIDO.metaTitle,
    description: CONTENIDO.metaDescription,
  },
};

/**
 * Datos estructurados.
 *
 * `FAQPage` se construye a partir del **mismo** array que se pinta más abajo.
 * Marcar como FAQ preguntas que no están visibles en la página es una
 * infracción explícita de las directrices de Google, y la forma más fácil de
 * cometerla es mantener dos listas.
 *
 * No hay `offers` ni `aggregateRating` en `SoftwareApplication`: no existe
 * pricing en el producto ni reseñas reales, y ambos son campos que Google
 * verifica contra la página. Inventarlos para conseguir una estrella en el
 * resultado es exactamente el fraude que penaliza.
 */
function datosEstructurados() {
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${SITE_URL}/#organization`,
        name: SITE_NAME,
        url: SITE_URL,
        description: CONTENIDO.metaDescription,
      },
      {
        "@type": "WebSite",
        "@id": `${SITE_URL}/#website`,
        name: SITE_NAME,
        url: SITE_URL,
        publisher: { "@id": `${SITE_URL}/#organization` },
        inLanguage: "es-ES",
      },
      {
        "@type": "SoftwareApplication",
        name: SITE_NAME,
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        description: CONTENIDO.metaDescription,
        url: SITE_URL,
      },
      {
        "@type": "FAQPage",
        mainEntity: CONTENIDO.faq.map((f) => ({
          "@type": "Question",
          name: f.pregunta,
          acceptedAnswer: { "@type": "Answer", text: f.respuesta },
        })),
      },
    ],
  };
}

export default function LandingPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(datosEstructurados()) }}
      />

      {/* Portada */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-16 pt-20 md:pt-28">
        <h1 className="max-w-[20ch] font-display text-4xl font-bold leading-[1.08] tracking-[-0.03em] text-balance md:text-6xl">
          {CONTENIDO.h1}
        </h1>
        <p className="mt-6 max-w-[62ch] text-lg leading-relaxed text-muted-foreground md:text-xl">
          {CONTENIDO.subtitulo}
        </p>
        <div className="mt-10 flex flex-wrap items-center gap-3">
          <Link
            href="/login"
            className="inline-flex h-11 items-center justify-center rounded-md bg-primary px-6 text-sm font-semibold text-primary-foreground shadow transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {CONTENIDO.ctaPrimario}
          </Link>
          <Link
            href="#como-funciona"
            className="inline-flex h-11 items-center justify-center rounded-md border border-input px-6 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {CONTENIDO.ctaSecundario}
          </Link>
        </div>
      </section>

      {/* Cuerpo */}
      <div id="como-funciona" className="border-t border-border/60">
        <div className="mx-auto w-full max-w-6xl px-6 py-4">
          {CONTENIDO.secciones.map((seccion) => (
            <section
              key={seccion.h2}
              className="grid gap-6 border-b border-border/40 py-14 last:border-b-0 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:gap-14"
            >
              <h2 className="font-display text-2xl font-semibold leading-snug tracking-[-0.02em] text-pretty md:text-3xl">
                {seccion.h2}
              </h2>
              <div className="max-w-[68ch]">
                {seccion.parrafos.map((parrafo) => (
                  <p
                    key={parrafo}
                    className="mb-4 text-base leading-relaxed text-muted-foreground last:mb-0"
                  >
                    {parrafo}
                  </p>
                ))}
                {seccion.bullets && seccion.bullets.length > 0 && (
                  <ul className="mt-6 space-y-3">
                    {seccion.bullets.map((bullet) => (
                      <li
                        key={bullet}
                        className="relative pl-6 text-base leading-relaxed before:absolute before:left-0 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-primary"
                      >
                        {bullet}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          ))}
        </div>
      </div>

      {/* Preguntas frecuentes */}
      <div className="border-t border-border/60 bg-card/30">
        <section className="mx-auto w-full max-w-6xl px-6 py-16">
          <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
            Preguntas frecuentes
          </h2>
          <dl className="mt-10 grid gap-x-14 gap-y-9 md:grid-cols-2">
            {CONTENIDO.faq.map((item) => (
              <div key={item.pregunta} className="max-w-[58ch]">
                <dt className="text-base font-semibold leading-snug">{item.pregunta}</dt>
                <dd className="mt-2.5 text-base leading-relaxed text-muted-foreground">
                  {item.respuesta}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      {/* Cierre */}
      <section className="mx-auto w-full max-w-6xl px-6 py-20">
        <h2 className="max-w-[24ch] font-display text-2xl font-semibold tracking-[-0.02em] text-balance md:text-3xl">
          {CONTENIDO.cierreTitulo}
        </h2>
        <p className="mt-4 max-w-[62ch] text-base leading-relaxed text-muted-foreground">
          {CONTENIDO.cierreTexto}
        </p>
        <Link
          href="/login"
          className="mt-8 inline-flex h-11 items-center justify-center rounded-md bg-primary px-6 text-sm font-semibold text-primary-foreground shadow transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          {CONTENIDO.ctaPrimario}
        </Link>
      </section>
    </>
  );
}
