import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MapPin } from "lucide-react";
import { listarLicitaciones } from "@/lib/publico-api";
import { formatNumber } from "@/lib/utils";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaPublicaDePagina } from "@/lib/paginacion-hubs";
import { CCAA_SIN_ASIGNAR, rutaHubCcaa } from "@/lib/slug";
import { ListadoLicitaciones } from "./listado-licitaciones";
import { Paginacion } from "./paginacion";
import { CierrePublico } from "./cierre-publico";

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
 *
 * Lo sirven dos rutas con el mismo contenido: `licitaciones/[ccaa]` (página 1)
 * y `hub-paginado/licitaciones/[ccaa]/[pagina]`, a la que el proxy reescribe
 * `?p=N`. Ninguna de las dos lee la query, y por eso las dos van a la caché
 * ISR: ver `lib/paginacion-hubs.ts`.
 */

const POR_PAGINA = 50;

/** Nombre presentable a partir del slug, para titulares y metadatos. */
function nombreDesdeSlug(slug: string): string {
  if (slug === CCAA_SIN_ASIGNAR) return "sin comunidad autónoma asignada";
  return slug
    .split("-")
    .map((palabra) => (palabra.length > 2 ? palabra[0].toUpperCase() + palabra.slice(1) : palabra))
    .join(" ");
}

export function metadatosHubCcaa(ccaa: string, pagina: number): Metadata {
  const nombre = nombreDesdeSlug(ccaa);
  const titulo = `Licitaciones de tecnología en ${nombre}`;
  const descripcion = `Concursos públicos de tecnología en ${nombre}: objeto, órgano de contratación, presupuesto y plazos, con enlace al anuncio oficial.`;

  return {
    title: titulo,
    description: descripcion.slice(0, 160),
    // Canonical auto-referente **incluyendo la página**, y en su forma pública
    // (`?p=N`) aunque esta página se sirva desde el segmento interno. Apuntar
    // todas las páginas a la primera es el error clásico: Google descarta las
    // demás y con ellas los enlaces a las fichas que solo aparecen ahí.
    alternates: { canonical: rutaPublicaDePagina(rutaHubCcaa(ccaa), pagina) },
    openGraph: {
      ...OG_IMAGE_COMPARTIDA,
      title: titulo,
      description: descripcion.slice(0, 160),
      url: rutaHubCcaa(ccaa),
    },
    twitter: { ...TWITTER_COMPARTIDO, title: titulo, description: descripcion.slice(0, 160) },
  };
}

export async function paginaHubCcaa(ccaa: string, pagina: number) {
  const { items: licitaciones, total } = await listarLicitaciones({
    ccaa,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  // Un hub vacío es contenido delgado por definición: no hay nada que indexar
  // y, si Google lo rastrea, cuenta como página de baja calidad del dominio.
  // Un 404 es la respuesta correcta — pero solo cuando "vacío" es una respuesta
  // del backend y no un fallo de red disfrazado. `listarLicitaciones` lanza en
  // ese segundo caso (ver `lib/publico-api.ts`), de modo que la revalidación
  // horaria no puede sustituir un hub bueno por un 404 indexable. Una página
  // más allá de la última también llega vacía, y también es un 404.
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
