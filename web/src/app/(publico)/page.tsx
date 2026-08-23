import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Database,
  FileText,
  Gauge,
  Radar,
  ScanSearch,
  TrendingDown,
  Users,
  Workflow,
} from "lucide-react";
import { OG_IMAGE_COMPARTIDA, SITE_NAME, SITE_URL, TWITTER_COMPARTIDO } from "@/lib/site";
import { solicitarAccesoHref } from "@/lib/contacto";
import { CONTENIDO } from "./_content/landing";
import { HeroConsola } from "./_components/hero-consola";
import { EnlaceSolicitarAcceso } from "./_components/enlace-solicitar-acceso";

/**
 * Landing pública — la única página de TenderFlow que un buscador puede
 * indexar, y la primera pantalla de quien llega sin cuenta.
 *
 * Es un Server Component sin JavaScript de cliente para el contenido, a propósito
 * (la única isla es el beacon de analytics del CTA — ver
 * `_components/enlace-solicitar-acceso.tsx` —, cuyo ancla llega igualmente
 * renderizada en el HTML del servidor):
 * lo que un rastreador lee es el HTML de la respuesta, y todo lo que haya que
 * hidratar para que aparezca el texto es texto que Google puede no ver. Por la
 * misma razón todo el movimiento de la página es CSS puro (los primitivos
 * `animate-in`/`tf-stagger` de globals.css) y **ningún contenido depende del
 * scroll para hacerse visible**: una entrada al cargar termina sola; un reveal
 * al hacer scroll dejaría texto en `opacity: 0` para un rastreador que no
 * scrollea.
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

/* Iconografía por posición, fuera del contenido: el copy es dato puro y la
 * elección visual pertenece a la maquetación. Mismo orden que los arrays de
 * `landing.ts`; ante un desajuste de longitud se cae al primero. */
const ICONOS_PILARES = [Radar, TrendingDown, Users];
const ICONOS_SECCIONES = [ScanSearch, Database, Gauge, TrendingDown, Users, FileText, Workflow];

/* Los CTA a /login comparten piel en el hero y en el cierre; una sola
 * constante evita que las dos copias diverjan en el siguiente retoque.
 * Transición con propiedades explícitas (nunca `transition: all`) y feedback
 * de pulsación en `active:` — emil-design-eng: un botón tiene que sentirse
 * pulsado, y la curva es la `--ease-out` de la casa. */
const CTA_PRIMARIO =
  "group inline-flex h-11 items-center justify-center gap-2 rounded-md bg-primary px-6 " +
  "text-sm font-semibold text-primary-foreground shadow-md " +
  "transition-[transform,background-color,box-shadow] duration-150 ease-out " +
  "hover:bg-primary/90 active:scale-[0.97] focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 " +
  "focus-visible:ring-offset-background";

const CTA_SECUNDARIO =
  "inline-flex h-11 items-center justify-center rounded-md border border-input " +
  "bg-background/60 px-6 text-sm font-medium " +
  "transition-[transform,background-color,border-color] duration-150 ease-out " +
  "hover:bg-accent hover:text-accent-foreground active:scale-[0.97] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* Entrada del hero: única animación de la página (frecuencia "rara" — una vez
 * por visita — y propósito de delight, el caso que la skill permite). Cadencia
 * de 60ms vía `tf-stagger` en el contenedor; el resto de la página se pinta
 * quieta y legible desde el primer frame. */
const ENTRADA_HERO = "animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-500";

/* CTA de acceso. El destino lo decide `solicitarAccesoHref` (lib/contacto):
 * mailto con asunto prellenado cuando el entorno define el email de contacto,
 * /login con atribución UTM cuando no. El ancla la pinta la isla
 * `EnlaceSolicitarAcceso` para emitir el evento de analytics del clic — un
 * mailto no genera pageview y sin evento el CTA principal sería un punto
 * ciego. El href se calcula aquí, en servidor. */
function CtaAcceso({ utmContent }: { utmContent: string }) {
  return (
    <EnlaceSolicitarAcceso href={solicitarAccesoHref(utmContent)} ubicacion={utmContent} className={CTA_PRIMARIO}>
      {CONTENIDO.ctaPrimario}
      <ArrowRight
        className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </EnlaceSolicitarAcceso>
  );
}

export default function LandingPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(datosEstructurados()) }} />

      {/* Portada */}
      <section className="relative overflow-hidden">
        <div aria-hidden="true" className="tf-hero-grid absolute inset-0 -z-10" />
        <div className="mx-auto grid w-full max-w-6xl items-center gap-14 px-6 pt-16 pb-20 md:pt-24 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:gap-12">
          <div className="tf-stagger">
            <p
              className={`${ENTRADA_HERO} border-primary/30 bg-primary/[0.06] text-primary inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-[11px] font-medium tracking-wider uppercase`}
            >
              <Radar className="h-3.5 w-3.5" aria-hidden="true" />
              {CONTENIDO.eyebrow}
            </p>
            <h1
              className={`${ENTRADA_HERO} font-display mt-6 max-w-[22ch] text-4xl leading-[1.06] font-bold tracking-[-0.03em] text-balance md:text-5xl`}
            >
              {CONTENIDO.h1}
            </h1>
            <p
              className={`${ENTRADA_HERO} text-muted-foreground mt-6 max-w-[58ch] text-base leading-relaxed md:text-lg`}
            >
              {CONTENIDO.subtitulo}
            </p>
            <div className={`${ENTRADA_HERO} mt-9 flex flex-wrap items-center gap-3`}>
              <CtaAcceso utmContent="hero" />
              <Link href="#como-funciona" className={CTA_SECUNDARIO}>
                {CONTENIDO.ctaSecundario}
              </Link>
            </div>
            <p className={`${ENTRADA_HERO} text-muted-foreground mt-5 text-xs leading-relaxed`}>
              {CONTENIDO.notaFuentes}
            </p>
          </div>

          {/* En una columna (móvil/tablet) la ilustración no debe estirarse a
              todo el ancho: se acota y centra; en lg vuelve a su columna. */}
          <div className="mx-auto w-full max-w-xl lg:mx-0 lg:max-w-none">
            <HeroConsola />
          </div>
        </div>
      </section>

      {/* Diccionario de familias: la forma más rápida de decir "esto es
          tecnología enterprise, no toda la contratación" es enseñar la lista. */}
      <section aria-label="Familias de producto cubiertas" className="border-border/60 bg-card/40 border-y">
        <div className="mx-auto w-full max-w-6xl px-6 py-10">
          <p className="text-muted-foreground max-w-[70ch] text-sm leading-relaxed">{CONTENIDO.familiasTitulo}</p>
          <ul className="mt-5 flex flex-wrap gap-2">
            {CONTENIDO.familias.map((familia) => (
              <li
                key={familia}
                className="border-border/70 bg-background/70 text-foreground/75 rounded-md border px-3 py-1.5 font-mono text-xs font-medium"
              >
                {familia}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Cómo funciona: las tres decisiones, en tres tarjetas */}
      <section id="como-funciona" className="mx-auto w-full max-w-6xl scroll-mt-24 px-6 py-20">
        <p className="text-primary font-mono text-xs tracking-widest uppercase">{CONTENIDO.ctaSecundario}</p>
        <h2 className="font-display mt-3 max-w-[26ch] text-2xl leading-snug font-semibold tracking-[-0.02em] text-balance md:text-3xl">
          Tres decisiones sobre un mismo corpus acotado
        </h2>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {CONTENIDO.pilares.map((pilar, i) => {
            const Icono = ICONOS_PILARES[i] ?? ICONOS_PILARES[0];
            return (
              <article key={pilar.titulo} className="border-border/70 bg-card relative rounded-xl border p-6 shadow-sm">
                <span aria-hidden="true" className="text-muted-foreground/60 absolute top-5 right-5 font-mono text-xs">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="bg-primary/10 text-primary flex h-10 w-10 items-center justify-center rounded-lg">
                  <Icono className="h-5 w-5" aria-hidden="true" />
                </span>
                <h3 className="font-display mt-4 text-lg font-semibold tracking-[-0.01em]">{pilar.titulo}</h3>
                <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{pilar.texto}</p>
              </article>
            );
          })}
        </div>
      </section>

      {/* Cuerpo en detalle */}
      <div className="border-border/60 border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-4">
          {CONTENIDO.secciones.map((seccion, i) => {
            const Icono = ICONOS_SECCIONES[i] ?? ICONOS_SECCIONES[0];
            return (
              <section
                key={seccion.h2}
                className="border-border/40 grid gap-6 border-b py-14 last:border-b-0 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:gap-14"
              >
                {/* La columna de cabecera acompaña al texto largo con sticky:
                    en pantallas cortas el lector nunca pierde de vista en qué
                    parte del producto está. */}
                <div className="md:sticky md:top-24 md:self-start">
                  <p className="text-primary flex items-center gap-2.5 font-mono text-xs tracking-widest uppercase">
                    <span aria-hidden="true" className="text-muted-foreground/60">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <Icono className="h-4 w-4" aria-hidden="true" />
                    {seccion.kicker}
                  </p>
                  <h2 className="font-display mt-3 text-2xl leading-snug font-semibold tracking-[-0.02em] text-pretty md:text-3xl">
                    {seccion.h2}
                  </h2>
                </div>
                <div className="max-w-[68ch]">
                  {seccion.parrafos.map((parrafo) => (
                    <p key={parrafo} className="text-muted-foreground mb-4 text-base leading-relaxed last:mb-0">
                      {parrafo}
                    </p>
                  ))}
                  {seccion.bullets && seccion.bullets.length > 0 && (
                    <ul className="mt-6 space-y-3">
                      {seccion.bullets.map((bullet) => (
                        <li key={bullet} className="flex gap-3 text-base leading-relaxed">
                          <Check className="text-primary mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                          {bullet}
                        </li>
                      ))}
                    </ul>
                  )}
                  {seccion.enlace && (
                    <Link
                      href={seccion.enlace.href}
                      className="group text-primary mt-6 inline-flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline"
                    >
                      {seccion.enlace.texto}
                      <ArrowRight
                        className="h-3.5 w-3.5 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </Link>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {/* Preguntas frecuentes */}
      <div className="border-border/60 bg-card/30 border-t">
        <section className="mx-auto w-full max-w-6xl px-6 py-16">
          <p className="text-primary font-mono text-xs tracking-widest uppercase">FAQ</p>
          <h2 className="font-display mt-3 text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
            Preguntas frecuentes
          </h2>
          <dl className="mt-10 grid gap-x-14 gap-y-8 md:grid-cols-2">
            {CONTENIDO.faq.map((item) => (
              <div key={item.pregunta} className="border-border/50 max-w-[58ch] border-t pt-6">
                <dt className="text-base leading-snug font-semibold">{item.pregunta}</dt>
                <dd className="text-muted-foreground mt-2.5 text-sm leading-relaxed md:text-base">{item.respuesta}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      {/* Explorar los datos.
          No es un bloque de navegación decorativo: es el único enlace desde la
          portada —la página con más autoridad del sitio— hacia la superficie
          indexable. Sin él, los hubs y las fichas quedan colgando solo del
          sitemap, que los hace rastreables pero no les transmite relevancia. */}
      <div className="border-border/60 border-t">
        <section className="mx-auto w-full max-w-6xl px-6 py-16">
          <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
            Explora los concursos publicados
          </h2>
          <p className="text-muted-foreground mt-3 max-w-[62ch] text-base leading-relaxed">
            El anuncio oficial de cada licitación es consultable sin cuenta: objeto, órgano de contratación,
            presupuesto, plazos y lotes, con enlace al perfil del contratante.
          </p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            <Link
              href="/licitaciones"
              className="group border-border/70 bg-card hover:border-primary/40 focus-visible:ring-ring focus-visible:ring-offset-background flex items-center justify-between gap-4 rounded-xl border p-6 transition-[transform,border-color,box-shadow] duration-200 ease-out hover:shadow-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.99]"
            >
              <span className="min-w-0">
                <span className="font-display block text-lg font-semibold tracking-[-0.01em]">
                  Por comunidad autónoma
                </span>
                <span className="text-muted-foreground mt-1 block text-sm leading-relaxed">
                  Los anuncios abiertos de cada territorio, con su hub indexable.
                </span>
              </span>
              <ArrowUpRight
                className="text-muted-foreground group-hover:text-primary h-5 w-5 shrink-0 transition-[transform,color] duration-200 ease-out group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </Link>
            <Link
              href="/cpv"
              className="group border-border/70 bg-card hover:border-primary/40 focus-visible:ring-ring focus-visible:ring-offset-background flex items-center justify-between gap-4 rounded-xl border p-6 transition-[transform,border-color,box-shadow] duration-200 ease-out hover:shadow-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.99]"
            >
              <span className="min-w-0">
                <span className="font-display block text-lg font-semibold tracking-[-0.01em]">Por código CPV</span>
                <span className="text-muted-foreground mt-1 block text-sm leading-relaxed">
                  Software y servicios TI, agrupados por el código de la fuente.
                </span>
              </span>
              <ArrowUpRight
                className="text-muted-foreground group-hover:text-primary h-5 w-5 shrink-0 transition-[transform,color] duration-200 ease-out group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </Link>
          </div>
        </section>
      </div>

      {/* Cierre */}
      <section className="border-border/60 relative overflow-hidden border-t">
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_70%_90%_at_50%_100%,hsl(var(--primary)/0.10),transparent_72%)]"
        />
        <div className="mx-auto w-full max-w-6xl px-6 py-24 text-center">
          <h2 className="font-display mx-auto max-w-[24ch] text-3xl font-semibold tracking-[-0.02em] text-balance md:text-4xl">
            {CONTENIDO.cierreTitulo}
          </h2>
          <p className="text-muted-foreground mx-auto mt-5 max-w-[62ch] text-base leading-relaxed md:text-lg">
            {CONTENIDO.cierreTexto}
          </p>
          <div className="mt-9 flex justify-center">
            <CtaAcceso utmContent="cierre" />
          </div>
          <p className="text-muted-foreground mt-5 text-xs">{CONTENIDO.cierreNota}</p>
        </div>
      </section>
    </>
  );
}
