import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Landmark } from "lucide-react";
import { listarLicitaciones, obtenerHubs } from "@/lib/publico-api";
import { formatNumber } from "@/lib/utils";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaPublicaDePagina } from "@/lib/paginacion-hubs";
import { esSlugOrgano, rutaHubOrgano } from "@/lib/slug";
import { ListadoLicitaciones } from "./listado-licitaciones";
import { Paginacion } from "./paginacion";
import { CierrePublico } from "./cierre-publico";

/**
 * Hub público por órgano de contratación (F6.5).
 *
 * Responde a quien busca «licitaciones <ayuntamiento>» desde un buscador. Usa
 * la misma allowlist de columnas que el resto de la superficie pública: el
 * listado sale de `/publico/licitaciones?organo=` y el nombre del órgano, de
 * `/publico/hubs`, así que la página no expone nada que no viaje ya en cada
 * ficha pública (`scripts/check_public_surface.py`).
 *
 * El nombre **no** se reconstruye desde el slug, al revés que el hub de CCAA:
 * un órgano es un nombre largo y con mayúsculas propias («Consejería de…»), y
 * adivinarlo desde `consejeria-de-…` daría un titular falso. Si el slug no
 * está entre los hubs del backend —que ya aplican el umbral de volumen— la
 * página es un 404: no hay nombre que poner y sería contenido delgado.
 *
 * Lo sirven dos rutas con el mismo contenido: `licitaciones/organo/[slug]`
 * (página 1) y `hub-paginado/licitaciones/organo/[slug]/[pagina]`, a la que el
 * proxy reescribe `?p=N`. Ninguna de las dos lee la query, y por eso las dos
 * van a la caché ISR: ver `lib/paginacion-hubs.ts`.
 */

const POR_PAGINA = 50;

/** El hub del órgano, o `null` si el backend no le da página. */
async function hubDe(slug: string) {
  if (!esSlugOrgano(slug)) return null;
  const { organo } = await obtenerHubs();
  return (organo ?? []).find((hub) => hub.slug === slug) ?? null;
}

export async function metadatosHubOrgano(slug: string, pagina: number): Promise<Metadata> {
  const hub = await hubDe(slug);
  if (!hub) return {};

  const titulo = `Licitaciones de ${hub.nombre}`;
  const descripcion = `Concursos públicos de tecnología publicados por ${hub.nombre}: objeto, presupuesto y plazos, con enlace al anuncio oficial.`;
  return {
    title: titulo,
    description: descripcion.slice(0, 160),
    // Canonical auto-referente incluyendo la página, en su forma pública
    // (`?p=N`), como los otros hubs.
    alternates: { canonical: rutaPublicaDePagina(rutaHubOrgano(slug), pagina) },
    openGraph: {
      ...OG_IMAGE_COMPARTIDA,
      title: titulo,
      description: descripcion.slice(0, 160),
      url: rutaHubOrgano(slug),
    },
    twitter: { ...TWITTER_COMPARTIDO, title: titulo, description: descripcion.slice(0, 160) },
  };
}

export async function paginaHubOrgano(slug: string, pagina: number) {
  const hub = await hubDe(slug);
  if (!hub) notFound();

  const { items: licitaciones, total } = await listarLicitaciones({
    organo: slug,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  // Vacío = el backend contestó y no hay nada (p. ej. una página más allá de
  // la última). Un fallo de la API lanza en `listarLicitaciones` y la copia
  // ISR anterior se sigue sirviendo (ver `lib/publico-api.ts`).
  if (licitaciones.length === 0) notFound();

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: "Licitaciones", ruta: "/licitaciones" },
    { nombre: "Órganos de contratación", ruta: "/licitaciones/organo" },
    { nombre: hub.nombre, ruta: rutaHubOrgano(slug) },
  ];

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(migasJsonLd(migas)) }} />

      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <p className="text-primary flex flex-wrap items-center gap-x-3 gap-y-1.5 font-mono text-xs tracking-widest uppercase">
          <span className="flex items-center gap-2">
            <Landmark className="h-4 w-4" aria-hidden="true" />
            Por órgano de contratación
          </span>
          {/* El total lo da el endpoint del listado: aquí no se cuenta nada. */}
          <span className="text-muted-foreground border-border/60 bg-card/60 rounded-full border px-2.5 py-0.5 font-sans text-xs font-medium tracking-normal normal-case">
            {formatNumber(total)} publicadas
          </span>
        </p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones de {hub.nombre}
        </h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          Concursos públicos con componente de tecnología enterprise publicados por {hub.nombre}. Cada ficha enlaza al
          anuncio original del perfil del contratante.
        </p>

        <ListadoLicitaciones licitaciones={licitaciones} jsonLdNombre={`Licitaciones de ${hub.nombre}`} />

        <Paginacion base={rutaHubOrgano(slug)} paginaActual={pagina} total={total} porPagina={POR_PAGINA} />

        <CierrePublico ubicacion="hub-organo" />
      </div>
    </>
  );
}
