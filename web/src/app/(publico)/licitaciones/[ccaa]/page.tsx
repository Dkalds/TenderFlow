import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MapPin } from "lucide-react";
import { listarLicitaciones } from "@/lib/publico-api";
import { formatNumber } from "@/lib/utils";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { CCAA_SIN_ASIGNAR, rutaHubCcaa } from "@/lib/slug";
import { ListadoLicitaciones } from "@/app/(publico)/_components/listado-licitaciones";
import { Paginacion } from "@/app/(publico)/_components/paginacion";
import { CierrePublico } from "@/app/(publico)/_components/cierre-publico";

/**
 * Hub de licitaciones por comunidad autónoma.
 *
 * Responde a la consulta más frecuente del sector —"licitaciones <provincia>"—
 * y es la página que reparte autoridad hacia las fichas individuales.
 *
 * El segmento es un **slug** y la traducción al valor real de la columna la
 * hace Postgres (`_CCAA_SLUG_SQL` en `db/repositories/publico.py`). Aquí no hay
 * tabla de nombres: el invariante 3 de `web/AGENTS.md` prohíbe hardcodear en el
 * cliente listas que el backend debe proveer, y una tabla escrita a mano
 * divergiría en cuanto la fuente publicara una grafía nueva.
 */

type Params = { ccaa: string };
type Query = { p?: string };

/** Página solicitada, saneada. Cualquier basura cae en la 1. */
function paginaDe(query: Query): number {
  const n = Number(query.p);
  return Number.isInteger(n) && n > 1 ? n : 1;
}

const POR_PAGINA = 50;

/** Nombre presentable a partir del slug, para titulares y metadatos. */
function nombreDesdeSlug(slug: string): string {
  if (slug === CCAA_SIN_ASIGNAR) return "sin comunidad autónoma asignada";
  return slug
    .split("-")
    .map((palabra) => (palabra.length > 2 ? palabra[0].toUpperCase() + palabra.slice(1) : palabra))
    .join(" ");
}

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Query>;
}): Promise<Metadata> {
  const { ccaa } = await params;
  const pagina = paginaDe(await searchParams);
  const nombre = nombreDesdeSlug(ccaa);
  const titulo = `Licitaciones de tecnología en ${nombre}`;
  const descripcion = `Concursos públicos de tecnología en ${nombre}: objeto, órgano de contratación, presupuesto y plazos, con enlace al anuncio oficial.`;

  return {
    title: titulo,
    description: descripcion.slice(0, 160),
    // Canonical auto-referente **incluyendo la página**. Apuntar todas las
    // páginas a la primera es el error clásico: Google descarta las demás y con
    // ellas los enlaces a las fichas que solo aparecen ahí.
    alternates: { canonical: pagina > 1 ? `${rutaHubCcaa(ccaa)}?p=${pagina}` : rutaHubCcaa(ccaa) },
    openGraph: {
      ...OG_IMAGE_COMPARTIDA,
      title: titulo,
      description: descripcion.slice(0, 160),
      url: rutaHubCcaa(ccaa),
    },
    twitter: { ...TWITTER_COMPARTIDO, title: titulo, description: descripcion.slice(0, 160) },
  };
}

export default async function HubCcaa({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Query>;
}) {
  const { ccaa } = await params;
  const pagina = paginaDe(await searchParams);
  const { items: licitaciones, total } = await listarLicitaciones({
    ccaa,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  // Un hub vacío es contenido delgado por definición: no hay nada que indexar
  // y, si Google lo rastrea, cuenta como página de baja calidad del dominio.
  // Un 404 es la respuesta correcta.
  if (licitaciones.length === 0) notFound();

  const nombre = nombreDesdeSlug(ccaa);
  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre, ruta: rutaHubCcaa(ccaa) },
  ];

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(migasJsonLd(migas)) }} />

      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <p className="text-primary flex flex-wrap items-center gap-x-3 gap-y-1.5 font-mono text-xs tracking-widest uppercase">
          <span className="flex items-center gap-2">
            <MapPin className="h-4 w-4" aria-hidden="true" />
            Por comunidad autónoma
          </span>
          {/* El total lo da el endpoint del listado: aquí no se cuenta nada. */}
          <span className="text-muted-foreground border-border/60 bg-card/60 rounded-full border px-2.5 py-0.5 font-sans text-xs font-medium tracking-normal normal-case">
            {formatNumber(total)} publicadas
          </span>
        </p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones de tecnología en {nombre}
        </h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          Concursos públicos con componente de tecnología enterprise publicados por órganos de contratación{" "}
          {nombre === "sin comunidad autónoma asignada" ? "sin comunidad asignada en la fuente" : `de ${nombre}`}. Cada
          ficha enlaza al anuncio original del perfil del contratante.
        </p>

        <ListadoLicitaciones licitaciones={licitaciones} jsonLdNombre={`Licitaciones en ${nombre}`} />

        <Paginacion base={rutaHubCcaa(ccaa)} paginaActual={pagina} total={total} porPagina={POR_PAGINA} />

        <CierrePublico ubicacion="hub-ccaa" />
      </div>
    </>
  );
}

export const revalidate = 3600;
