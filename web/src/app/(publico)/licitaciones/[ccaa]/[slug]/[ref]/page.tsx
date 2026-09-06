import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { obtenerLicitacion, type LicitacionPublica } from "@/lib/publico-api";
import { TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubCcaa, rutaLicitacion } from "@/lib/slug";
import { formatCurrency } from "@/lib/utils";
import { CierrePublico } from "@/app/(publico)/_components/cierre-publico";
import { AtribucionFuente } from "@/app/(publico)/_components/ficha-atribucion";
import { CabeceraFicha, type Miga } from "@/app/(publico)/_components/ficha-cabecera";
import { DatosDelAnuncio } from "@/app/(publico)/_components/ficha-datos";
import { LotesLicitacion } from "@/app/(publico)/_components/ficha-lotes";

/**
 * Ficha pública de una licitación.
 *
 * Solo el anuncio oficial: nada de scoring, predicción de baja, escenarios de
 * precio ni adjudicatario. La proyección la impone el backend
 * (`db/repositories/publico.py`) y `scripts/check_public_surface.py` la
 * verifica en CI, pero conviene saberlo también al editar esta página.
 *
 * La ruta lleva cuatro segmentos —`/licitaciones/{ccaa}/{slug}/{ref}`— y la
 * referencia va suelta en el último. Ver `lib/slug.ts`: el alfabeto base64url
 * incluye `-`, así que pegarla al slug haría imposible saber dónde acaba uno.
 *
 * Presentación: los tres datos que deciden si el anuncio interesa
 * (presupuesto, fecha límite, publicación) van como destacados y el resto en la
 * tabla de datos; las dos listas y su disciplina —valores del endpoint tal
 * cual, ADR-014— viven en `_components/ficha-datos.tsx`, y el resto de bloques
 * en sus `ficha-*` hermanos. Aquí quedan los metadatos, el JSON-LD y el orden.
 */

type Params = { ccaa: string; slug: string; ref: string };

function descripcionSeo(lic: LicitacionPublica): string {
  const partes = [
    lic.organo_contratacion,
    lic.importe ? `Presupuesto ${formatCurrency(lic.importe)}` : null,
    lic.ccaa,
    lic.cpv ? `CPV ${lic.cpv}` : null,
  ].filter(Boolean);
  return `${partes.join(" · ")}. Anuncio oficial, plazos y lotes.`.slice(0, 160);
}

/** Las migas, que se pintan y se marcan: una sola lista para las dos cosas. */
function migasDe(lic: LicitacionPublica): Miga[] {
  return [
    { nombre: "Inicio", ruta: "/" },
    { nombre: lic.ccaa ?? "Sin comunidad", ruta: rutaHubCcaa(lic.ccaa) },
    {
      nombre: lic.titulo,
      ruta: rutaLicitacion({ ccaa: lic.ccaa, titulo: lic.titulo, ref: lic.ref }),
    },
  ];
}

/**
 * Metadatos de la ficha.
 *
 * Comparte llamada con el cuerpo de la página: Next deduplica el `fetch` dentro
 * de la misma request, así que pedir el anuncio dos veces cuesta una.
 *
 * Aquí **no se captura** el fallo de la API, aunque una excepción en
 * `generateMetadata` tumbe la página entera. Es justo lo que se busca: si no se
 * pudo preguntar, la regeneración ISR debe fallar para que Next conserve la
 * copia anterior. La alternativa —devolver el `noindex` de abajo cuando en
 * realidad no sabemos si el expediente existe— es peor que un 500: le pediría a
 * Google que desindexe una ficha viva por un timeout de red. Y capturar solo
 * aquí tampoco arreglaría nada, porque el cuerpo lanzaría a continuación.
 */
export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { ref } = await params;
  const lic = await obtenerLicitacion(ref);
  // `null` es ausencia afirmada por la API (404/410), no "no pude saberlo".
  if (!lic) return { title: "Licitación no encontrada", robots: { index: false } };

  // El canonical se calcula desde el dato **actual**, no desde la URL que se
  // pidió. Si el órgano corrige el título, el slug cambia pero la referencia
  // no: la URL antigua sigue resolviendo y se declara a sí misma como copia de
  // la nueva, en vez de competir con ella en el índice.
  const canonical = rutaLicitacion({ ccaa: lic.ccaa, titulo: lic.titulo, ref: lic.ref });
  const descripcion = descripcionSeo(lic);

  // Aquí NO se esparce `OG_IMAGE_COMPARTIDA`: este segmento tiene su propia
  // `opengraph-image.tsx` con los datos del anuncio, y los metadatos por
  // convención de fichero tienen prioridad. Declarar además la genérica
  // emitiría dos `og:image` compitiendo.
  return {
    title: lic.titulo.slice(0, 70),
    description: descripcion,
    alternates: { canonical },
    openGraph: {
      title: lic.titulo.slice(0, 70),
      description: descripcion,
      url: canonical,
      type: "article",
    },
    twitter: { ...TWITTER_COMPARTIDO, title: lic.titulo.slice(0, 70), description: descripcion },
  };
}

export default async function FichaLicitacion({ params }: { params: Promise<Params> }) {
  const { ref } = await params;
  const lic = await obtenerLicitacion(ref);

  // 404 **solo** si la API dijo 404. Si no se pudo preguntar, `obtenerLicitacion`
  // lanza y esta línea no se alcanza: con ISR eso conserva la ficha ya generada,
  // y en una URL nunca generada devuelve un 500 —que Googlebot reintenta— en vez
  // de un 404 que la borra del índice. Ver `lib/publico-api.ts`.
  if (!lic) notFound();

  const migas = migasDe(lic);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(migasJsonLd(migas)) }} />

      <article className="mx-auto w-full max-w-4xl px-6 py-12">
        <CabeceraFicha lic={lic} migas={migas} />

        <DatosDelAnuncio lic={lic} />

        <LotesLicitacion lotes={lic.lotes ?? []} />

        <AtribucionFuente lic={lic} />

        {/* Las dos salidas de la ficha, ambas secundarias: seguir navegando el
            corpus, o entrar con una cuenta que ya se tiene.

            El botón principal era este segundo enlace, y mandaba a /login a
            quien acababa de descubrir el producto. El alta self-service está
            apagada en producción (`lib/contacto.ts`): allí no hay registro que
            completar, sólo un formulario que responde 403 a quien no ha sido
            invitado. La ficha es la página que más tráfico orgánico recibe y su
            único CTA era, literalmente, una puerta cerrada.

            utm_content=ficha se conserva: en Vercel Analytics sigue viéndose
            cuántos llegan a /login desde una ficha indexada. */}
        <div className="mt-10 flex flex-wrap gap-3">
          <Link
            href={rutaHubCcaa(lic.ccaa)}
            className="border-input hover:bg-accent hover:text-accent-foreground inline-flex h-10 items-center rounded-md border px-5 text-sm font-medium transition-[transform,background-color,border-color] duration-150 ease-out active:scale-[0.97]"
          >
            Más licitaciones {lic.ccaa ? `en ${lic.ccaa}` : ""}
          </Link>
          <Link
            href="/login?utm_source=publico&utm_content=ficha"
            className="border-input hover:bg-accent hover:text-accent-foreground inline-flex h-10 items-center rounded-md border px-5 text-sm font-medium transition-[transform,background-color,border-color] duration-150 ease-out active:scale-[0.97]"
          >
            Ya tengo cuenta
          </Link>
        </div>

        {/* El cierre que sí lleva a alguna parte, el mismo de los hubs: dice qué
            hay dentro que no esté en el anuncio y solicita acceso por el canal
            que existe. `ubicacion="ficha"` separa su evento `solicitar_acceso`
            del de los hubs, que es la comparación que interesa — cuál de las dos
            superficies orgánicas convierte. */}
        <CierrePublico ubicacion="ficha" />
      </article>
    </>
  );
}

// Los `ccaa` y `slug` de la URL son decorativos: la referencia identifica el
// expediente por sí sola. Se aceptan tal cual en vez de validarlos contra el
// dato para no convertir un enlace con el slug antiguo en un 404 — el
// `canonical` de `generateMetadata` ya le dice a Google cuál es la buena.
export const dynamicParams = true;
export const revalidate = 3600;
