import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hubsOrganoAnunciables, obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubOrgano } from "@/lib/slug";
import { cn, formatNumber } from "@/lib/utils";
import { KICKER, TITULO_PAGINA } from "../../_components/piel-publica";

/**
 * Índice de hubs por órgano de contratación (F6.5).
 *
 * Existe por lo mismo que `/licitaciones`: un hub que sólo está en el sitemap
 * se rastrea, pero nada le transmite autoridad. Lista los mismos órganos que
 * el sitemap —los de más de diez anuncios, `hubsOrganoAnunciables`— para que
 * índice y sitemap no anuncien cosas distintas. Totales del backend (ADR-014).
 */

const TITULO = "Licitaciones por órgano de contratación";
const DESCRIPCION =
  "Concursos públicos de tecnología agrupados por el órgano que los publica: ayuntamientos, consejerías, ministerios y entidades públicas.";

export const metadata: Metadata = {
  title: TITULO,
  description: DESCRIPCION,
  alternates: { canonical: "/licitaciones/organo" },
  openGraph: { ...OG_IMAGE_COMPARTIDA, title: TITULO, description: DESCRIPCION, url: "/licitaciones/organo" },
  twitter: { ...TWITTER_COMPARTIDO, title: TITULO, description: DESCRIPCION },
};

export const revalidate = 3600;

/* Tarjeta de un índice: la tarjeta entera es el enlace, así que no lleva
 * flecha; al pasar el ratón cambian el filete y el color del nombre, nada se
 * desplaza ni gana sombra. */
const TARJETA_INDICE =
  "group border-border/70 bg-card focus-visible:ring-ring hover:border-primary/50 block rounded-xl border px-5 py-4 transition-colors focus-visible:ring-2 focus-visible:outline-none";

export default async function IndiceOrganos() {
  const organos = hubsOrganoAnunciables(await obtenerHubs());
  // Sin órganos con volumen no hay índice: contenido delgado, 404.
  if (organos.length === 0) notFound();

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: "Licitaciones", ruta: "/licitaciones" },
    { nombre: "Órganos de contratación", ruta: "/licitaciones/organo" },
  ];
  const entradas = organos.map((hub) => ({ titulo: hub.nombre, ruta: rutaHubOrgano(hub.slug) }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializarJsonLd([migasJsonLd(migas), listaJsonLd(TITULO, entradas)]) }}
      />

      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <p className={KICKER}>Por órgano de contratación</p>
        <h1 className={cn(TITULO_PAGINA, "mt-3")}>{TITULO}</h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">{DESCRIPCION}</p>

        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {organos.map((hub) => (
            <li key={hub.slug}>
              <Link href={rutaHubOrgano(hub.slug)} className={TARJETA_INDICE}>
                <span className="block min-w-0">
                  <span className="group-hover:text-primary line-clamp-2 block text-sm font-semibold transition-colors">
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
      </div>
    </>
  );
}
