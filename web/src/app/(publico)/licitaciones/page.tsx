import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hubsOrganoAnunciables, obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubCcaa } from "@/lib/slug";
import { cn, formatNumber } from "@/lib/utils";
import { KICKER, TARJETA_INDICE, TITULO_PAGINA } from "../_components/piel-publica";

/**
 * Índice de la superficie de licitaciones, por comunidad autónoma.
 *
 * Es el nodo que faltaba. Sin él pasaban dos cosas: `/licitaciones` devolvía
 * 404 —pese a que `robots.txt` abre ese prefijo y a que borrar el último
 * segmento de una URL es comportamiento normal de usuario— y, sobre todo, los
 * hubs por comunidad no recibían **ningún enlace interno**: existían en el
 * sitemap, así que Google los rastreaba, pero nada les transmitía autoridad. Un
 * sitemap dice "existo"; los enlaces dicen "importo".
 *
 * Los totales por comunidad vienen del endpoint de hubs: aquí no se cuenta
 * nada (ADR-014), solo se pinta con el mismo lenguaje visual de la landing.
 */

export const metadata: Metadata = {
  title: "Licitaciones públicas de tecnología en España",
  description:
    "Concursos públicos de tecnología por comunidad autónoma: objeto, órgano de contratación, presupuesto y plazos, con enlace al anuncio oficial.",
  alternates: { canonical: "/licitaciones" },
  openGraph: {
    ...OG_IMAGE_COMPARTIDA,
    title: "Licitaciones públicas de tecnología en España",
    description: "Concursos públicos de tecnología por comunidad autónoma.",
    url: "/licitaciones",
  },
  twitter: {
    ...TWITTER_COMPARTIDO,
    title: "Licitaciones públicas de tecnología en España",
    description: "Concursos públicos de tecnología por comunidad autónoma.",
  },
};

export const revalidate = 3600;

export default async function IndiceLicitaciones() {
  const hubs = await obtenerHubs();
  const { ccaa } = hubs;
  // El enlace al índice de órganos sólo si ese índice tiene algo: enlazar a un
  // 404 desde la página que reparte autoridad sería gastarla en nada.
  const hayOrganos = hubsOrganoAnunciables(hubs).length > 0;

  // Un índice sin nada que indexar es contenido delgado. Mejor 404 que una
  // página vacía que Google cuente contra la calidad del dominio.
  //
  // La condición dice lo que parece **desde que `obtenerHubs` distingue "no hay
  // hubs" de "no pude preguntar"** (ver `lib/publico-api.ts`). Antes no: un
  // fallo de red devolvía la misma lista vacía, y como esta ruta es ISR, la
  // revalidación que pillaba la API fría sustituía el índice bueno por un 404
  // que se servía durante la hora siguiente. Ahora ese caso lanza: la
  // regeneración falla, Next conserva la copia anterior y lo reintenta. Este
  // `notFound()` solo se ejecuta cuando el backend afirmó que no hay hubs.
  if (ccaa.length === 0) notFound();

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: "Licitaciones", ruta: "/licitaciones" },
  ];
  const entradas = ccaa.map((hub) => ({ titulo: hub.nombre, ruta: rutaHubCcaa(hub.slug) }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: serializarJsonLd([migasJsonLd(migas), listaJsonLd("Licitaciones por comunidad autónoma", entradas)]),
        }}
      />

      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <p className={KICKER}>Por comunidad autónoma</p>
        <h1 className={cn(TITULO_PAGINA, "mt-3")}>Licitaciones públicas de tecnología en España</h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          Concursos con componente de tecnología enterprise publicados por la administración española, agrupados por
          comunidad autónoma. Los datos proceden de la Plataforma de Contratación del Sector Público y de TED, y cada
          ficha enlaza al anuncio original.
        </p>

        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ccaa.map((hub) => (
            <li key={hub.slug}>
              <Link href={rutaHubCcaa(hub.slug)} className={TARJETA_INDICE}>
                <span className="block min-w-0">
                  <span className="group-hover:text-primary block truncate text-sm font-semibold transition-colors">
                    {hub.nombre}
                  </span>
                  <span className="text-muted-foreground tf-tnum text-tf-meta mt-0.5 block">
                    {formatNumber(hub.total)} licitaciones
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>

        <p className="text-muted-foreground mt-10 text-sm">
          ¿Buscas por tipo de contrato?{" "}
          <Link href="/cpv" className="text-foreground font-medium underline underline-offset-4">
            Índice por código CPV
          </Link>
          {hayOrganos && (
            <>
              {" "}
              ·{" "}
              <Link href="/licitaciones/organo" className="text-foreground font-medium underline underline-offset-4">
                Índice por órgano de contratación
              </Link>
            </>
          )}
          .
        </p>
      </div>
    </>
  );
}
