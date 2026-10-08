/**
 * Cómo se nombra el enlace externo de una licitación según su fuente.
 *
 * La ficha rotulaba ese enlace «Ver en PLACSP» sin mirar de dónde venía el
 * expediente, y desde ADR-009 el corpus es multi-fuente: con `ted` el href va a
 * ted.europa.eu, con `pscp` a la plataforma catalana, con `euskadi_rss` a
 * euskadi.eus. El texto prometía un portal y abría otro.
 *
 * El campo `fuente` del DTO es la única señal fiable: `id_externo` solo lleva
 * namespace (`ted:123`) en las fuentes nuevas —PLACSP es el legacy sin
 * prefijo—, y adivinar por el host del href convierte un dato del backend en
 * una heurística del frontend.
 *
 * Una fuente que no esté en el mapa cae en la etiqueta genérica: es cierta para
 * cualquier portal y no obliga a tocar esto cada vez que entra un conector.
 */

/** Para una fuente que el frontend todavía no sabe nombrar. Nunca miente. */
const ETIQUETA_GENERICA = "Ver en la plataforma del comprador";

/** `licitaciones.fuente` → nombre del portal al que lleva su `url`. */
const ETIQUETAS: Record<string, string> = {
  placsp: "Ver en PLACSP",
  ted: "Ver en TED",
  pscp: "Ver en PSCP",
  euskadi_rss: "Ver en Contratación Pública de Euskadi",
  galicia_rss: "Ver en Contratos de Galicia",
};

/** Host del anuncio en TED. Ver `esEnlaceDeTed`. */
const HOST_TED = "ted.europa.eu";

/**
 * TED es la única fuente cuyo `url` no siempre lleva a su propio portal.
 *
 * Desde `82c0683` el conector prefiere BT-15 —el enlace donde el comprador
 * cuelga los pliegos— y solo cae al PDF de ted.europa.eu cuando ese campo falta
 * o no lleva a ningún expediente. Sobre la muestra de ese commit, dos de cada
 * tres convocatorias acababan en un deeplink de PLACSP, y el resto en
 * contractaciopublica.cat, portalcontratacion.navarra.es… Rotular todas «Ver en
 * TED» es el mismo fallo que este módulo existe para cerrar, una fuente más
 * allá, así que aquí sí se mira el destino: no es adivinar la fuente —la
 * sabemos— sino distinguir las dos salidas que el propio conector elige.
 */
function esEnlaceDeTed(url: string | null | undefined): boolean {
  if (!url) return false;
  try {
    const { hostname } = new URL(url);
    return hostname === HOST_TED || hostname.endsWith(`.${HOST_TED}`);
  } catch {
    // Un `url` que no parsea no permite afirmar nada sobre su destino.
    return false;
  }
}

/**
 * Texto del enlace externo («Ver en TED», «Ver en PLACSP»…).
 *
 * Sirve igual como texto visible y como `aria-label` de un enlace de solo
 * icono: es la misma promesa en los dos sitios. `url` solo hace falta para
 * `ted`; omitirlo degrada esa fuente a la etiqueta genérica, nunca a una falsa.
 */
export function fuenteLinkLabel(
  fuente: string | null | undefined,
  url?: string | null,
): string {
  const clave = fuente?.trim().toLowerCase();
  if (!clave) return ETIQUETA_GENERICA;
  if (clave === "ted") return esEnlaceDeTed(url) ? ETIQUETAS.ted : ETIQUETA_GENERICA;
  if (clave in ETIQUETAS) return ETIQUETAS[clave];
  // Los conectores derivados de PLACSP namespacean su fuente
  // (`placsp_watched_company_awards`, y una por lote en los backfills:
  // `..._bulk_202601`). Mismo portal, misma etiqueta; enumerarlos sería
  // perseguir un nombre que crece con cada mes cargado.
  if (clave.startsWith("placsp")) return ETIQUETAS.placsp;
  return ETIQUETA_GENERICA;
}

/** Cómo se nombra un portal en una celda: corto a la vista, completo en la pista. */
export interface OrigenFuente {
  corta: string;
  nombre: string;
}

/** `licitaciones.fuente` → nombre del portal de origen. Mismas claves que `ETIQUETAS`. */
const ORIGENES: Record<string, OrigenFuente> = {
  placsp: { corta: "PLACSP", nombre: "Plataforma de Contratación del Sector Público" },
  ted: { corta: "TED", nombre: "Diario Oficial de la Unión Europea (TED)" },
  pscp: { corta: "PSCP", nombre: "Plataforma de Serveis de Contractació Pública" },
  euskadi_rss: { corta: "Euskadi", nombre: "Contratación Pública de Euskadi" },
  galicia_rss: { corta: "Galicia", nombre: "Contratos de Galicia" },
};

/** Para una fuente que existe pero que el frontend todavía no sabe nombrar. */
const ORIGEN_GENERICO: OrigenFuente = { corta: "Otra", nombre: "Otra plataforma de contratación" };

/**
 * De qué portal viene un expediente (la columna «Origen»). A diferencia de
 * `fuenteLinkLabel`, aquí no importa adónde lleva el enlace: un anuncio de TED
 * es de TED aunque sus pliegos estén en PLACSP. Sin fuente devuelve `null` y la
 * celda pinta la raya de vacío; una fuente desconocida se dice como «Otra».
 */
export function fuenteOrigen(fuente: string | null | undefined): OrigenFuente | null {
  const clave = fuente?.trim().toLowerCase();
  if (!clave) return null;
  if (clave in ORIGENES) return ORIGENES[clave];
  if (clave.startsWith("placsp")) return ORIGENES.placsp;
  return ORIGEN_GENERICO;
}
