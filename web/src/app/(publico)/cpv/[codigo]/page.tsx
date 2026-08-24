import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Hash } from "lucide-react";
import { listarLicitaciones } from "@/lib/publico-api";
import { formatNumber } from "@/lib/utils";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubCpv } from "@/lib/slug";
import { ListadoLicitaciones } from "@/app/(publico)/_components/listado-licitaciones";
import { Paginacion } from "@/app/(publico)/_components/paginacion";

/**
 * Hub por código CPV.
 *
 * El CPV es el vocabulario común de contratación pública de la UE, y buena
 * parte del público objetivo busca literalmente por código ("licitaciones CPV
 * 72000000"). El segmento acepta un prefijo, así que `/cpv/72` cubre la
 * división entera y `/cpv/72222300` un código concreto.
 */

type Params = { codigo: string };
type Query = { p?: string };

/** Página solicitada, saneada. Cualquier basura cae en la 1. */
function paginaDe(query: Query): number {
  const n = Number(query.p);
  return Number.isInteger(n) && n > 1 ? n : 1;
}

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

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Query>;
}): Promise<Metadata> {
  const { codigo } = await params;
  const pagina = paginaDe(await searchParams);
  const division = descripcionDivision(codigo);
  const titulo = `Licitaciones CPV ${codigo}`;
  const descripcion = division
    ? `Concursos públicos con código CPV ${codigo} — ${division}. Objeto, órgano de contratación, presupuesto y plazos.`
    : `Concursos públicos con código CPV ${codigo}: objeto, órgano de contratación, presupuesto y plazos.`;

  return {
    title: titulo,
    description: descripcion.slice(0, 160),
    // Auto-referente incluyendo la página: si todas apuntaran a la primera,
    // Google descartaría el resto junto con sus enlaces a las fichas.
    alternates: {
      canonical: pagina > 1 ? `${rutaHubCpv(codigo)}?p=${pagina}` : rutaHubCpv(codigo),
    },
    openGraph: {
      ...OG_IMAGE_COMPARTIDA,
      title: titulo,
      description: descripcion.slice(0, 160),
      url: rutaHubCpv(codigo),
    },
    twitter: { ...TWITTER_COMPARTIDO, title: titulo, description: descripcion.slice(0, 160) },
  };
}

export default async function HubCpv({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Query>;
}) {
  const { codigo } = await params;
  const pagina = paginaDe(await searchParams);

  // El backend valida el formato, pero comprobarlo aquí evita una llamada de
  // red por cada URL inventada que un rastreador se encuentre por ahí.
  if (!/^\d{2,8}$/.test(codigo)) notFound();

  const { items: licitaciones, total } = await listarLicitaciones({
    cpv: codigo,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  if (licitaciones.length === 0) notFound();

  const division = descripcionDivision(codigo);
  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: `CPV ${codigo}`, ruta: rutaHubCpv(codigo) },
  ];

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(migasJsonLd(migas)) }} />

      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <p className="text-primary flex flex-wrap items-center gap-x-3 gap-y-1.5 font-mono text-xs tracking-widest uppercase">
          <span className="flex items-center gap-2">
            <Hash className="h-4 w-4" aria-hidden="true" />
            Por código CPV
          </span>
          {/* El total lo da el endpoint del listado: aquí no se cuenta nada. */}
          <span className="text-muted-foreground border-border/60 bg-card/60 rounded-full border px-2.5 py-0.5 font-sans text-xs font-medium tracking-normal normal-case">
            {formatNumber(total)} publicadas
          </span>
        </p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones CPV {codigo}
        </h1>
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
      </div>
    </>
  );
}

export const revalidate = 3600;
