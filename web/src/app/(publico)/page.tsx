import type { Metadata } from "next";
import { OG_IMAGE_COMPARTIDA, SITE_NAME, SITE_URL, TWITTER_COMPARTIDO } from "@/lib/site";
import { LEGAL_RESPONSABLE } from "@/lib/legal";
import { serializarJsonLd } from "@/lib/jsonld";
import { CONTENIDO } from "./_content/landing";
import { FranjaDatos } from "./_components/franja-datos";
import { HeroLanding } from "./_components/landing-hero";
import { ComoFuncionaLanding } from "./_components/landing-como-funciona";
import { SeccionesLanding } from "./_components/landing-secciones";
import { FaqLanding } from "./_components/landing-faq";
import { ExplorarLanding } from "./_components/landing-explorar";
import { CierreLanding } from "./_components/landing-cierre";

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
 * ## Qué queda en este fichero
 *
 * El orden de los bloques, los metadatos y el JSON-LD. Cada bloque vive en
 * `_components/landing-*.tsx` con el porqué de su composición al lado; la piel
 * que comparten (los dos CTA, el kicker, la entrada del hero) está en
 * `_components/landing-piel.ts`, que es lo que impide que diverjan.
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
 * `FAQPage` se construye a partir del **mismo** array que pinta
 * `landing-faq.tsx`. Marcar como FAQ preguntas que no están visibles en la
 * página es una infracción explícita de las directrices de Google, y la forma
 * más fácil de cometerla es mantener dos listas.
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

export default function LandingPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(datosEstructurados()) }} />

      <HeroLanding />

      {/* Las tres cifras reales del corpus. */}
      <FranjaDatos />

      <ComoFuncionaLanding />
      <SeccionesLanding />
      <FaqLanding />
      <ExplorarLanding />
      <CierreLanding />
    </>
  );
}
