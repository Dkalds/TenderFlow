import { Fragment } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { getImageProps } from "next/image";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { OG_IMAGE_COMPARTIDA, SITE_NAME, SITE_URL, TWITTER_COMPARTIDO } from "@/lib/site";
import { solicitarAccesoHref } from "@/lib/contacto";
import { LEGAL_RESPONSABLE } from "@/lib/legal";
import { CONTENIDO } from "./_content/landing";
import { MarcoCaptura } from "./_components/marco-captura";
import { FranjaDatos } from "./_components/franja-datos";
import { UltimosPublicados } from "./_components/ultimos-publicados";
import { FormularioSolicitud } from "./_components/formulario-solicitud";
import { EnlaceSolicitarAcceso } from "./_components/enlace-solicitar-acceso";
import capturaHero from "./_assets/radar-hero.webp";
import capturaHeroMovil from "./_assets/radar-hero-movil.webp";
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
 * animación infinita.
 *
 * ## La composición, y por qué cambió (2026-09)
 *
 * La versión anterior era el esqueleto por defecto de una landing de SaaS:
 * píldora con icono, titular centrado, dos botones, captura con cromo de
 * ventana de tres puntos, tres tarjetas con su icono en un cuadrado tintado y
 * sus numerales `01/02/03` en monoespaciada, retícula de fondo con máscara
 * radial y un resplandor en el cierre. Cada pieza estaba bien resuelta y el
 * conjunto se leía como una plantilla — que es exactamente lo que un comprador
 * de software empresarial no quiere ver antes de dejar su correo.
 *
 * Lo que hay ahora es una composición editorial: alineada a la izquierda,
 * separada por filetes en vez de tarjetas, con la tipografía y el dato haciendo
 * la jerarquía. El ornamento que se fue no se ha sustituido por otro ornamento.
 *
 * El cambio de fondo está en el hero: donde había una **foto** del producto hay
 * cinco expedientes **reales**, servidos por la API pública (ver
 * `_components/ultimos-publicados.tsx`). Un producto cuyo argumento es la
 * calidad del dato no puede abrir con una captura de datos de demostración; la
 * captura sigue existiendo, pero baja a la sección que explica cómo se trabaja.
 *
 * `title.absolute` evita la plantilla `%s | TenderFlow` que declara el layout
 * raíz: en la portada duplicaría la marca ("TenderFlow … | TenderFlow") y se
 * comería caracteres del título en el resultado de búsqueda.
 */
/**
 * La landing consulta la API para la franja de cifras y el extracto de
 * anuncios, y declara `revalidate` igual que el resto de la superficie pública:
 * las dos llamadas ocurren al generar, no en cada visita. Hasta que el layout
 * raíz dejó de leer `headers()` esto no habría servido de nada — la app entera
 * se renderizaba por request.
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
        // El nombre legal sólo se declara si el entorno lo publica de verdad:
        // `lib/legal.ts` devuelve `null` tanto si falta como si lleva un valor
        // de relleno, y un `legalName` inventado en el JSON-LD sería la misma
        // mentira que el aviso legal con un placeholder dentro.
        ...(LEGAL_RESPONSABLE ? { legalName: LEGAL_RESPONSABLE } : {}),
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

/* Los CTA a la solicitud comparten piel en el hero, en el intermedio y en el
 * cierre; una sola constante evita que las copias diverjan en el siguiente
 * retoque. Transición con propiedades explícitas (nunca `transition: all`) y
 * feedback de pulsación en `active:` — emil-design-eng: un botón tiene que
 * sentirse pulsado, y la curva es la `--ease-out` de la casa. */
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

/* Enlace de "Explorar". Ya no es una tarjeta con borde y sombra: la sección
 * entera pasó a filete, así que aquí basta con la fila y su flecha. */
const FILA_EXPLORAR =
  "group flex items-baseline justify-between gap-4 border-b border-border/50 py-5 " +
  "transition-colors duration-150 ease-out hover:border-primary/40 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* Entrada del hero: única animación de la página (frecuencia "rara" — una vez
 * por visita — y propósito de delight, el caso que la skill permite). Cadencia
 * de 60ms vía `tf-stagger` en el contenedor; el resto de la página se pinta
 * quieta y legible desde el primer frame. */
const ENTRADA_HERO = "animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-500";

/* Kicker de sección: versalita fina, sin píldora ni icono. El anterior era una
 * cápsula con borde, fondo tintado y un icono dentro — el gesto más reconocible
 * de una plantilla de SaaS. */
const KICKER = "text-muted-foreground text-xs font-medium tracking-[0.14em] uppercase";

/* CTA de acceso. El destino lo decide `solicitarAccesoHref` (lib/contacto) y
 * hoy es siempre el ancla del formulario de esta misma página: sus dos
 * versiones anteriores —un `mailto:` dependiente de una variable de entorno, y
 * /login como fallback— no llevaban a ninguna parte utilizable.
 *
 * El ancla la pinta la isla `EnlaceSolicitarAcceso` para emitir el evento de
 * analytics del clic. Ojo con lo que ese evento mide: **intención, no
 * conversión**. Desde que el destino es un fragmento, pulsar el botón es un
 * scroll, no un envío. La conversión la reporta la página de gracias
 * (`solicitud-recibida`), que es la única que sabe si el POST prosperó; las
 * dos métricas juntas son las que dan el embudo. `utmContent` distingue de qué
 * CTA vino el clic — header, hero, intermedio— y por eso hay más de uno. */
function CtaAcceso({ utmContent }: { utmContent: string }) {
  return (
    <EnlaceSolicitarAcceso href={solicitarAccesoHref()} ubicacion={utmContent} className={CTA_PRIMARIO}>
      {CONTENIDO.ctaPrimario}
      <ArrowRight
        className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </EnlaceSolicitarAcceso>
  );
}

/* Captura del producto, con art direction.

   Una consola de escritorio completa reducida a los ~342 px de un móvil es
   ilegible: el texto de la tabla queda por debajo de 2 px. Por eso en pantallas
   estrechas se sirve un recorte del panel de detalle —el score, su banda y el
   desglose de las seis dimensiones—, que es estrecho por naturaleza y cuenta la
   misma historia a un tamaño que se lee.

   Va con `<picture>` y no con dos `<Image>` y clases `hidden`, porque con CSS
   el navegador se descarga las dos variantes; aquí sólo baja la que aplica.
   Las dimensiones se declaran en el `<source>` para que el navegador reserve la
   caja correcta antes de decodificar y no haya salto.

   Ya **no** lleva `priority`: desde que el hero enseña dato y no una foto, el
   LCP es texto y esta imagen está por debajo del fold. Marcarla como prioritaria
   competiría con lo que sí hay que pintar primero. */
const SIZES_ANCHA = "(min-width: 1152px) 1104px, calc(100vw - 3rem)";
const SIZES_ESTRECHA = "calc(100vw - 3rem)";

function CapturaProducto() {
  const comun = { alt: CONTENIDO.capturaAlt };
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
      <img {...resto} srcSet={estrecha} alt={CONTENIDO.capturaAlt} loading="lazy" className="h-auto w-full" />
    </picture>
  );
}

export default function LandingPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(datosEstructurados()) }} />

      {/* Portada.

          Dos columnas en escritorio: el argumento a la izquierda, el dato a la
          derecha. No es una retícula decorativa — es la tesis de la página
          puesta en el espacio: lo que se promete, y al lado la prueba, sin que
          haya que bajar para encontrarla. En móvil se apilan en ese mismo orden.

          El texto va alineado a la izquierda. Centrado sobre una imagen a
          sangre era lo que pedía la composición anterior; con una columna de
          medida legible, centrar sólo dificulta la lectura. */}
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

      {/* Las tres cifras reales del corpus. */}
      <FranjaDatos />

      {/* Cómo funciona: las tres decisiones, en tres columnas separadas por
          filete. Eran tarjetas con borde, sombra, un icono dentro de un
          cuadrado tintado y un numeral en monoespaciada arriba a la derecha:
          cuatro capas de adorno para tres párrafos. */}
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

      {/* Cuerpo en detalle: tres secciones, cada una con su cabecera a la
          izquierda y el texto a la derecha. El kicker ya no lleva icono ni
          numeral — el filete y la posición bastan para saber dónde se está. */}
      <div className="border-border/60 border-t">
        <div className="mx-auto w-full max-w-6xl px-6">
          {CONTENIDO.secciones.map((seccion) => (
            <Fragment key={seccion.h2}>
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

              {/* Único punto de conversión intermedio.

                  El formulario vive al final de la página y el botón del hero
                  salta hasta allí, así que entre una cosa y otra no había dónde
                  actuar: quien terminaba de leer de dónde sale cada número —el
                  momento de más intención— tenía que seguir bajando o irse. Va
                  justo después de esa sección y no repartido por todas: un
                  reclamo cada dos párrafos convierte el argumento en un folleto. */}
              {seccion.icono === "scoring" && (
                <div className="border-border/40 flex flex-wrap items-center justify-between gap-x-8 gap-y-4 border-b py-10">
                  <div className="max-w-[46ch]">
                    <p className="font-display text-lg font-semibold tracking-[-0.01em]">
                      {CONTENIDO.ctaIntermedioTitulo}
                    </p>
                    <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
                      {CONTENIDO.ctaIntermedioTexto}
                    </p>
                  </div>
                  <CtaAcceso utmContent="intermedio" />
                </div>
              )}
            </Fragment>
          ))}
        </div>
      </div>

      {/* Preguntas frecuentes */}
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
          <div className="border-border/50 mt-8 border-t">
            {CONTENIDO.explorar.map((destino) => (
              <Link key={destino.href} href={destino.href} className={FILA_EXPLORAR}>
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

      {/* Cierre. Sin el resplandor radial de fondo: el gradiente decorativo
          detrás del último bloque es otro de los gestos por defecto, y aquí
          competía con el único formulario de la página. */}
      <section className="border-border/60 border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          {/* `lg` y no `md`: a 768 px el contenedor deja 664 px para las dos
                pistas, la fija se lleva sus 32rem y a la columna de texto le
                quedaban 152 px — el titular se salía de su caja. A partir de
                1024 px hay sitio de sobra para las dos. */}
            <div className="grid gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
            <div>
              <h2 className="font-display max-w-[18ch] text-3xl font-semibold tracking-[-0.02em] text-balance md:text-4xl">
                {CONTENIDO.cierreTitulo}
              </h2>
              <p className="text-muted-foreground mt-5 max-w-[52ch] text-base leading-relaxed">
                {CONTENIDO.cierreTexto}
              </p>
              <p className="text-muted-foreground mt-5 text-xs">{CONTENIDO.cierreNota}</p>
              {/* Quién hay detrás, en la misma pantalla en la que se pide un
                  correo. Sólo si el entorno publica una identidad real:
                  `lib/legal.ts` devuelve `null` cuando falta o cuando lleva un
                  valor de relleno. */}
              {LEGAL_RESPONSABLE && (
                <p className="text-muted-foreground mt-2 text-xs">
                  {CONTENIDO.responsablePrefijo}{" "}
                  <span className="text-foreground/80 font-medium">{LEGAL_RESPONSABLE}</span>
                </p>
              )}
            </div>
            {/* El destino del CTA, aquí mismo. Los tres botones saltan a este
                ancla en vez de abrir un cliente de correo. */}
            <FormularioSolicitud />
          </div>
        </div>
      </section>
    </>
  );
}
