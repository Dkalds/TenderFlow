import type { Metadata } from "next";
import Link from "next/link";
import Image, { getImageProps } from "next/image";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Database,
  FileText,
  Gauge,
  Radar,
  TrendingDown,
  Users,
  Workflow,
} from "lucide-react";
import { OG_IMAGE_COMPARTIDA, SITE_NAME, SITE_URL, TWITTER_COMPARTIDO } from "@/lib/site";
import { solicitarAccesoHref } from "@/lib/contacto";
import { CONTENIDO, type IconoLanding } from "./_content/landing";
import { MarcoCaptura } from "./_components/marco-captura";
import { FranjaDatos } from "./_components/franja-datos";
import { FormularioSolicitud } from "./_components/formulario-solicitud";
import { EnlaceSolicitarAcceso } from "./_components/enlace-solicitar-acceso";
import capturaHero from "./_assets/radar-hero.webp";
import capturaHeroMovil from "./_assets/radar-hero-movil.webp";
import capturaDetalle from "./_assets/detalle-corpus.webp";
import { serializarJsonLd } from "@/lib/jsonld";

/**
 * Landing pública — la única página de TenderFlow que un buscador puede
 * indexar, y la primera pantalla de quien llega sin cuenta.
 *
 * El contenido es Server Component y no depende de hidratación: lo que un
 * rastreador lee es el HTML de la respuesta, y todo lo que haya que hidratar
 * para que aparezca el texto es texto que Google puede no ver. La única isla
 * cliente es el beacon de analytics del CTA (ver
 * `_components/enlace-solicitar-acceso.tsx`), cuyo ancla llega igualmente
 * renderizada desde el servidor; el formulario de solicitud es HTML nativo y
 * envía sin JavaScript.
 *
 * Ojo con la afirmación "sin JavaScript de cliente", que este comentario hacía
 * a secas y el build desmentía: es cierta de esta página, no del documento. El
 * layout raíz montaba los providers del dashboard —react-query, sesión,
 * tooltips— y con ellos ~170 KB comprimidos. Dejó de hacerlo, pero la
 * afirmación sólo se sostiene mientras nadie los devuelva ahí.
 *
 * Todo el movimiento es CSS puro (los primitivos `animate-in`/`tf-stagger` de
 * globals.css) y **ningún contenido depende del scroll para hacerse visible**:
 * una entrada al cargar termina sola; un reveal al hacer scroll dejaría texto
 * en `opacity: 0` para un rastreador que no scrollea. Tampoco queda ninguna
 * animación infinita — la había, un `animate-ping` sobre el fold, en el mock
 * que esta página ya no usa.
 *
 * `title.absolute` evita la plantilla `%s | TenderFlow` que declara el layout
 * raíz: en la portada duplicaría la marca ("TenderFlow … | TenderFlow") y se
 * comería caracteres del título en el resultado de búsqueda.
 */
/**
 * La landing no consulta datos, pero declara `revalidate` igual que el resto de
 * la superficie pública: deja la ruta en el mismo régimen ISR y documenta que
 * es estática a propósito. Hasta que el layout raíz dejó de leer `headers()`
 * esto no habría servido de nada — la app entera se renderizaba por request.
 */
export const revalidate = 3600;

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

/* Iconografía fuera del contenido: el copy es dato puro y la elección visual
 * pertenece a la maquetación. La correspondencia va por clave y no por
 * posición — con arrays paralelos, reordenar `landing.ts` desalineaba los
 * iconos sin un solo error de compilación, y el `?? ICONOS[0]` de rescate
 * enmascaraba el desajuste en vez de delatarlo. Este `Record` es exhaustivo:
 * añadir una clave al tipo sin darle icono no compila. */
const ICONOS: Record<IconoLanding, LucideIcon> = {
  radar: Radar,
  precio: TrendingDown,
  competencia: Users,
  corpus: Database,
  scoring: Gauge,
  pliegos: FileText,
  flujo: Workflow,
};

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

/* Piel de las tarjetas de "Explorar". Estaba copiada carácter a carácter en
 * las dos tarjetas —250 caracteres de clases, con su icono y su transición—,
 * la misma duplicación que los dos CTA ya habían evitado con una constante. */
const TARJETA_EXPLORAR =
  "group flex items-center justify-between gap-4 rounded-xl border border-border/70 bg-card p-6 " +
  "transition-[transform,border-color,box-shadow] duration-200 ease-out " +
  "hover:border-primary/40 hover:shadow-md active:scale-[0.99] " +
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

/* Captura del hero, con art direction.

   Una consola de escritorio completa reducida a los ~342 px de un móvil es
   ilegible: el texto de la tabla queda por debajo de 2 px. Por eso en pantallas
   estrechas se sirve un recorte del panel de detalle —el score, su banda y el
   desglose de las seis dimensiones—, que es estrecho por naturaleza y cuenta la
   misma historia a un tamaño que se lee.

   Va con `<picture>` y no con dos `<Image>` y clases `hidden`, porque con CSS
   el navegador se descarga las dos variantes; aquí sólo baja la que aplica.
   `priority` marca la imagen como `eager` + `fetchPriority="high"`: es el LCP
   de la página. Las dimensiones se declaran en el `<source>` para que el
   navegador reserve la caja correcta antes de decodificar y no haya salto. */
const SIZES_ANCHA = "(min-width: 1152px) 1104px, calc(100vw - 3rem)";
const SIZES_ESTRECHA = "calc(100vw - 3rem)";

function CapturaHero() {
  const comun = { alt: CONTENIDO.capturaHeroAlt, priority: true };
  const {
    props: { srcSet: ancha },
  } = getImageProps({ ...comun, src: capturaHero, sizes: SIZES_ANCHA });
  const {
    props: { srcSet: estrecha, ...resto },
  } = getImageProps({ ...comun, src: capturaHeroMovil, sizes: SIZES_ESTRECHA });

  return (
    <picture>
      {/* `sizes` va también en el `<source>`: sin él el navegador asume 100vw y
          se descarga la variante de 3840 px para un hueco de 1104. */}
      <source
        media="(min-width: 640px)"
        srcSet={ancha}
        sizes={SIZES_ANCHA}
        width={capturaHero.width}
        height={capturaHero.height}
      />
      {/* `loading`/`fetchPriority` explícitos: al desestructurar `srcSet` fuera
          de `props` se pierde la propagación, y esta imagen es el LCP. */}
      <img
        {...resto}
        srcSet={estrecha}
        alt={CONTENIDO.capturaHeroAlt}
        loading="eager"
        fetchPriority="high"
        className="h-auto w-full"
      />
    </picture>
  );
}

export default function LandingPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(datosEstructurados()) }} />

      {/* Portada.

          El hero enseñaba un mock CSS abstracto de la consola y la captura real
          vivía tres pantallas más abajo: la misma historia contada dos veces, y
          la versión pobre —sin texto, porque ADR-014 no permite inventar datos
          en el frontend— ocupando el espacio de más valor de la página. Queda
          una sola visualización, la de verdad, arriba.

          Con ella el LCP pasa a ser una imagen priorizable en vez del `h1`
          atado a la descarga de Space Grotesk. El texto se centra porque la
          captura ocupa el ancho completo: una columna alineada a la izquierda
          sobre una imagen a sangre queda descolgada. */}
      <section className="relative overflow-hidden">
        <div aria-hidden="true" className="tf-hero-grid absolute inset-0 -z-10" />
        <div className="mx-auto w-full max-w-6xl px-6 pt-16 pb-20 md:pt-24">
          <div className="tf-stagger mx-auto max-w-3xl text-center">
            <p
              className={`${ENTRADA_HERO} border-primary/30 bg-primary/[0.06] text-primary inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-[11px] font-medium tracking-wider uppercase`}
            >
              <Radar className="h-3.5 w-3.5" aria-hidden="true" />
              {CONTENIDO.eyebrow}
            </p>
            <h1
              className={`${ENTRADA_HERO} font-display mx-auto mt-6 max-w-[24ch] text-4xl leading-[1.06] font-bold tracking-[-0.03em] text-balance md:text-5xl`}
            >
              {CONTENIDO.h1}
            </h1>
            <p
              className={`${ENTRADA_HERO} text-muted-foreground mx-auto mt-6 max-w-[58ch] text-base leading-relaxed text-pretty md:text-lg`}
            >
              {CONTENIDO.subtitulo}
            </p>
            <div className={`${ENTRADA_HERO} mt-9 flex flex-wrap items-center justify-center gap-3`}>
              <CtaAcceso utmContent="hero" />
              <Link href="#como-funciona" className={CTA_SECUNDARIO}>
                {CONTENIDO.ctaSecundario}
              </Link>
            </div>
            <p className={`${ENTRADA_HERO} text-muted-foreground mx-auto mt-5 max-w-[62ch] text-xs leading-relaxed`}>
              {CONTENIDO.notaFuentes}
            </p>
          </div>

          <figure className={`${ENTRADA_HERO} mt-14`}>
            <MarcoCaptura etiqueta={CONTENIDO.capturaHeroEtiqueta}>
              <CapturaHero />
            </MarcoCaptura>
            <figcaption className="text-muted-foreground mt-3 text-center text-xs">{CONTENIDO.capturaNota}</figcaption>
          </figure>
        </div>
      </section>

      {/* Las tres cifras reales del corpus, justo después de la promesa del
          hero. Es un componente async: la página sigue siendo estática con ISR,
          así que la llamada ocurre al generar y no en cada visita. */}
      <FranjaDatos />

      {/* Cómo funciona: las tres decisiones, en tres tarjetas */}
      <section id="como-funciona" className="mx-auto w-full max-w-6xl scroll-mt-24 px-6 py-20">
        <p className="text-primary font-mono text-xs tracking-widest uppercase">{CONTENIDO.pilaresKicker}</p>
        <h2 className="font-display mt-3 max-w-[26ch] text-2xl leading-snug font-semibold tracking-[-0.02em] text-balance md:text-3xl">
          {CONTENIDO.pilaresTitulo}
        </h2>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {CONTENIDO.pilares.map((pilar, i) => {
            const Icono = ICONOS[pilar.icono];
            return (
              <article key={pilar.titulo} className="border-border/70 bg-card relative rounded-xl border p-6 shadow-sm">
                {/* Sin `/60`: a esa opacidad el numeral queda en 2,5:1 sobre el fondo
                    claro e incumple el mínimo de 4,5:1 de WCAG 1.4.3, que aplica a
                    todo texto visible aunque sea decorativo y lleve aria-hidden. */}
                <span aria-hidden="true" className="text-muted-foreground absolute top-5 right-5 font-mono text-xs">
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

      {/* Segunda pantalla del producto. Antes repetía el Radar —mismo cromo,
          mismas bandas, mismas seis dimensiones que el mock de arriba—; ahora
          que la consola está en el hero, aquí se enseña algo distinto: el
          corpus completo. Sin `priority`: está bajo el fold y el lazy nativo de
          next/image es exactamente lo que hace falta. */}
      <div className="border-border/60 bg-card/40 border-t">
        <section className="mx-auto w-full max-w-6xl px-6 py-20">
          <p className="text-primary font-mono text-xs tracking-widest uppercase">{CONTENIDO.capturaKicker}</p>
          <h2 className="font-display mt-3 max-w-[26ch] text-2xl leading-snug font-semibold tracking-[-0.02em] text-balance md:text-3xl">
            {CONTENIDO.capturaTitulo}
          </h2>
          <p className="text-muted-foreground mt-4 max-w-[64ch] text-base leading-relaxed">{CONTENIDO.capturaTexto}</p>

          <figure className="mt-10">
            <MarcoCaptura etiqueta={CONTENIDO.capturaEtiqueta}>
              <Image src={capturaDetalle} alt={CONTENIDO.capturaAlt} sizes={SIZES_ANCHA} className="h-auto w-full" />
            </MarcoCaptura>
            <figcaption className="text-muted-foreground mt-3 text-xs">{CONTENIDO.capturaNota}</figcaption>
          </figure>
        </section>
      </div>

      {/* Cuerpo en detalle */}
      <div className="border-border/60 border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-4">
          {CONTENIDO.secciones.map((seccion, i) => {
            const Icono = ICONOS[seccion.icono];
            return (
              <section
                key={seccion.h2}
                className="border-border/40 grid gap-6 border-b py-14 last:border-b-0 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:gap-14"
              >
                {/* La columna de cabecera acompaña al texto largo con sticky:
                    en pantallas cortas el lector nunca pierde de vista en qué
                    parte del producto está. */}
                {/* `top-16` y no `top-24`: el header sticky mide ~58 px, así que 96
                    dejaba 38 px de hueco muerto. `z-10` y fondo propio porque al
                    desanclarse la columna pasaba por debajo del header traslúcido y
                    su título se leía borroso a través del blur. */}
                <div className="bg-background md:sticky md:top-16 md:z-10 md:self-start md:pb-4">
                  <p className="text-primary flex items-center gap-2.5 font-mono text-xs tracking-widest uppercase">
                    <span aria-hidden="true" className="text-muted-foreground">
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
                  <ul className="mt-6 space-y-3">
                    {seccion.bullets.map((bullet) => (
                      <li key={bullet} className="flex gap-3 text-base leading-relaxed">
                        <Check className="text-primary mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                        {bullet}
                      </li>
                    ))}
                  </ul>
                  {/* El diccionario de familias era una franja suelta sin
                      encabezado —un bloque cargado de keywords invisible para
                      quien navega por títulos—. Vive donde se explica: dentro
                      de la sección que dice qué entra en el corpus. */}
                  {seccion.icono === "corpus" && (
                    <>
                      <p className="text-muted-foreground mt-8 text-sm leading-relaxed">{CONTENIDO.familiasTitulo}</p>
                      <ul className="mt-4 flex flex-wrap gap-2">
                        {CONTENIDO.familias.map((familia) => (
                          <li
                            key={familia}
                            className="border-border/70 bg-card text-foreground/75 rounded-md border px-3 py-1.5 font-mono text-xs font-medium"
                          >
                            {familia}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {seccion.enlaces && (
                    <div className="mt-6 flex flex-col gap-2">
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
          })}
        </div>
      </div>

      {/* Preguntas frecuentes */}
      <div className="border-border/60 bg-card/30 border-t">
        <section className="mx-auto w-full max-w-6xl px-6 py-16">
          <p className="text-primary font-mono text-xs tracking-widest uppercase">{CONTENIDO.faqKicker}</p>
          <h2 id="faq-titulo" className="font-display mt-3 text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
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

      {/* Explorar los datos.
          No es un bloque de navegación decorativo: es el único enlace desde la
          portada —la página con más autoridad del sitio— hacia la superficie
          indexable. Sin él, los hubs y las fichas quedan colgando solo del
          sitemap, que los hace rastreables pero no les transmite relevancia. */}
      <div className="border-border/60 border-t">
        <section className="mx-auto w-full max-w-6xl px-6 py-16">
          <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
            {CONTENIDO.explorarTitulo}
          </h2>
          <p className="text-muted-foreground mt-3 max-w-[62ch] text-base leading-relaxed">{CONTENIDO.explorarTexto}</p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {CONTENIDO.explorar.map((destino) => (
              <Link key={destino.href} href={destino.href} className={TARJETA_EXPLORAR}>
                <span className="min-w-0">
                  <span className="font-display block text-lg font-semibold tracking-[-0.01em]">{destino.titulo}</span>
                  <span className="text-muted-foreground mt-1 block text-sm leading-relaxed">{destino.texto}</span>
                </span>
                <ArrowUpRight
                  className="text-muted-foreground group-hover:text-primary h-5 w-5 shrink-0 transition-[transform,color] duration-200 ease-out group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                  aria-hidden="true"
                />
              </Link>
            ))}
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
          <p className="text-muted-foreground mt-5 text-xs">{CONTENIDO.cierreNota}</p>
          {/* El destino del CTA, aquí mismo. El botón del hero salta a este
              ancla en vez de abrir un cliente de correo. */}
          <FormularioSolicitud />
        </div>
      </section>
    </>
  );
}
