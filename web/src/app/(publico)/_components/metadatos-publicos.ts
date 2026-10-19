import type { Metadata } from "next";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";

/**
 * Metadatos de una página pública indexable: título, descripción, canonical,
 * Open Graph y Twitter card, a partir de una sola ruta.
 *
 * Una página que no declara `openGraph` hereda el de la raíz —`og:title`
 * «TenderFlow», la descripción genérica y ningún `og:url`—, así que al
 * compartirla se presenta como la portada. Y declarar `openGraph` a mano obliga
 * a acordarse de esparcir `OG_IMAGE_COMPARTIDA` y `TWITTER_COMPARTIDO` (ver
 * `lib/site.ts`). Aquí canonical y `og:url` salen del mismo valor: en los hubs
 * paginados divergían, y la página 3 se declaraba canónica de sí misma mientras
 * se compartía como la 1.
 */
export function metadatosPublicos({
  titulo,
  descripcion,
  ruta,
}: {
  titulo: string;
  descripcion: string;
  /** Ruta pública canónica, con su `?p=N` si es una página interna. */
  ruta: string;
}): Metadata {
  return {
    title: titulo,
    description: descripcion,
    alternates: { canonical: ruta },
    openGraph: { ...OG_IMAGE_COMPARTIDA, title: titulo, description: descripcion, url: ruta },
    twitter: { ...TWITTER_COMPARTIDO, title: titulo, description: descripcion },
  };
}

/** Longitud por defecto: el layout raíz añade « | TenderFlow» detrás. */
const MAX_TITULO = 58;

/**
 * Título recortado para `<title>`, `og:title` y la Twitter card, cortando entre
 * palabras y con una sola elipsis («…»). Con `max` ≥ 2 el resultado nunca
 * pasa de `max` caracteres, elipsis incluida.
 *
 * Sólo corta a mitad de palabra si la primera palabra ya no cabe; en ese caso
 * evita partir un par sustituto, como `truncate` de `lib/utils.ts`.
 */
export function tituloParaMetadatos(titulo: string, max = MAX_TITULO): string {
  const limpio = titulo.replace(/\s+/g, " ").trim();
  if (limpio.length <= max) return limpio;
  if (max < 2) return "…";

  const disponible = max - 1;
  const cabe = limpio.slice(0, disponible);
  const cortaEntrePalabras = limpio[disponible] === " ";
  const ultimoEspacio = cabe.lastIndexOf(" ");

  let cuerpo: string;
  if (cortaEntrePalabras) {
    cuerpo = cabe;
  } else if (ultimoEspacio > 0) {
    cuerpo = cabe.slice(0, ultimoEspacio);
  } else {
    const ultima = cabe.charCodeAt(cabe.length - 1);
    cuerpo = ultima >= 0xd800 && ultima <= 0xdbff ? cabe.slice(0, -1) : cabe;
  }

  // Una coma o un guion delante de la elipsis («Suministro de equipos,…») se lee
  // como un error tipográfico.
  const sinPuntuacion = cuerpo.replace(/[\s,;:.\-–—(/]+$/u, "");
  return `${sinPuntuacion || cuerpo}…`;
}
