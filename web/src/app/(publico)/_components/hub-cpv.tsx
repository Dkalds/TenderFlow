import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { listarLicitaciones } from "@/lib/publico-api";
import { cn, formatNumber } from "@/lib/utils";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaPublicaDePagina } from "@/lib/paginacion-hubs";
import { rutaHubCpv } from "@/lib/slug";
import { ListadoLicitaciones } from "./listado-licitaciones";
import { Paginacion } from "./paginacion";
import { CierrePublico } from "./cierre-publico";
import { KICKER, TITULO_PAGINA } from "./piel-publica";

/**
 * Hub por código CPV.
 *
 * El CPV es el vocabulario común de contratación pública de la UE, y buena
 * parte del público objetivo busca literalmente por código ("licitaciones CPV
 * 72000000"). El segmento acepta un prefijo, así que `/cpv/72` cubre la
 * división entera y `/cpv/72222300` un código concreto.
 *
 * Lo sirven dos rutas con el mismo contenido: `cpv/[codigo]` (página 1) y
 * `hub-paginado/cpv/[codigo]/[pagina]`, a la que el proxy reescribe `?p=N`.
 * Ninguna de las dos lee la query, y por eso las dos van a la caché ISR: ver
 * `lib/paginacion-hubs.ts`.
 */

const POR_PAGINA = 50;

/**
 * Etiqueta de la división CPV.
 *
 * Es una tabla, sí, pero no de las que prohíbe el invariante 3: el CPV es una
 * nomenclatura pública y estable de la UE, no un dato que el backend calcule.
 * Solo se listan las divisiones que el corpus puede contener — el filtro de
 * ingesta acota a 48 (software) y 72 (servicios TI).
 */
const DIVISIONES: Record<string, string> = {
  "48": "paquetes de software y sistemas de información",
  "72": "servicios de tecnologías de la información",
};

function descripcionDivision(codigo: string): string | null {
  return DIVISIONES[codigo.slice(0, 2)] ?? null;
}

export function metadatosHubCpv(codigo: string, pagina: number): Metadata {
  const division = descripcionDivision(codigo);
  const titulo = `Licitaciones CPV ${codigo}`;
  const descripcion = division
    ? `Concursos públicos con código CPV ${codigo} — ${division}. Objeto, órgano de contratación, presupuesto y plazos.`
    : `Concursos públicos con código CPV ${codigo}: objeto, órgano de contratación, presupuesto y plazos.`;

  return {
    title: titulo,
    description: descripcion.slice(0, 160),
    // Auto-referente incluyendo la página, y en su forma pública (`?p=N`)
    // aunque se sirva desde el segmento interno: si todas apuntaran a la
    // primera, Google descartaría el resto junto con sus enlaces a las fichas.
    alternates: { canonical: rutaPublicaDePagina(rutaHubCpv(codigo), pagina) },
    openGraph: {
      ...OG_IMAGE_COMPARTIDA,
      title: titulo,
      description: descripcion.slice(0, 160),
      url: rutaHubCpv(codigo),
    },
    twitter: { ...TWITTER_COMPARTIDO, title: titulo, description: descripcion.slice(0, 160) },
  };
}

export async function paginaHubCpv(codigo: string, pagina: number) {
  // El backend valida el formato, pero comprobarlo aquí evita una llamada de
  // red por cada URL inventada que un rastreador se encuentre por ahí.
  if (!/^\d{2,8}$/.test(codigo)) notFound();

  const { items: licitaciones, total } = await listarLicitaciones({
    cpv: codigo,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  // Vacío = el backend contestó y no hay nada bajo ese prefijo (o la página
  // está más allá de la última). Un fallo de la API no llega aquí:
  // `listarLicitaciones` lanza, la regeneración ISR falla y el hub anterior se
  // sigue sirviendo (ver `lib/publico-api.ts`).
  if (licitaciones.length === 0) notFound();

  const division = descripcionDivision(codigo);
  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: `CPV ${codigo}`, ruta: rutaHubCpv(codigo) },
  ];

  return (
    <>
      <script
        type="application/ld+json"
        // Semgrep (react-dangerouslysetinnerhtml) sigue lo que entra por parámetro
        // hasta `__html`, pero `serializarJsonLd` escapa `<` y el texto no puede
        // cerrar el bloque: ver `lib/jsonld.ts`. Falso positivo.
        // nosemgrep
        dangerouslySetInnerHTML={{ __html: serializarJsonLd(migasJsonLd(migas)) }}
      />

      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        {/* El rótulo de toda la superficie pública, con el total al lado: sin
            icono ni píldora. El total lo da el endpoint del listado; aquí no
            se cuenta nada. */}
        <p className={KICKER}>
          Por código CPV · <span className="tf-tnum">{formatNumber(total)}</span> publicadas
        </p>
        <h1 className={cn(TITULO_PAGINA, "mt-3")}>Licitaciones CPV {codigo}</h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          {division ? (
            <>
              Concursos públicos clasificados bajo el código CPV {codigo} —{" "}
              <span className="text-foreground">{division}</span>—, publicados por órganos de contratación españoles.
            </>
          ) : (
            <>
              Concursos públicos clasificados bajo el código CPV {codigo}, publicados por órganos de contratación
              españoles.
            </>
          )}{" "}
          Cada ficha enlaza al anuncio original del perfil del contratante.
        </p>

        <ListadoLicitaciones licitaciones={licitaciones} jsonLdNombre={`Licitaciones CPV ${codigo}`} />

        <Paginacion base={rutaHubCpv(codigo)} paginaActual={pagina} total={total} porPagina={POR_PAGINA} />

        <CierrePublico ubicacion="hub-cpv" />
      </div>
    </>
  );
}
