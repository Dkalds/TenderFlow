"use client";

import { SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import { documentosNuevos } from "@/lib/documento-nuevo";
import { ExternalLink, FileText } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { cn } from "@/lib/utils";

const TIPO_LABELS: Record<string, string> = {
  legal: "Pliego administrativo (PCAP)",
  technical: "Pliego técnico (PPT)",
  additional: "Documento adicional",
};

function hostDe(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function enDominio(host: string, dominio: string): boolean {
  return host === dominio || host.endsWith(`.${dominio}`);
}

/** Texto del enlace a `licitacion.url`. Cada fuente enlaza su propia
 *  plataforma: un aviso TED lleva a la del comprador o a su anuncio, y uno de
 *  Cataluña a la PSCP, así que «la ficha de PLACSP» no valía para todos. */
function textosFicha(url: string): { ver: string; verTodos: string } {
  const host = hostDe(url);
  if (enDominio(host, "contrataciondelestado.es")) {
    return { ver: "Ver en la ficha de PLACSP", verTodos: "Ver todos en la ficha de PLACSP" };
  }
  if (enDominio(host, "contractaciopublica.cat") || enDominio(host, "contractaciopublica.gencat.cat")) {
    return { ver: "Ver en la ficha de la PSCP", verTodos: "Ver todos en la ficha de la PSCP" };
  }
  if (enDominio(host, "ted.europa.eu")) {
    return { ver: "Ver el anuncio en TED", verTodos: "Ver el anuncio en TED" };
  }
  return { ver: "Ver en la plataforma del comprador", verTodos: "Ver todos en la plataforma del comprador" };
}

/** El anuncio TED entra como documento `additional` (la columna `tipo` no
 *  admite otro valor), pero no es un adjunto del pliego: se nombra por lo que es. */
function etiquetaTipo(doc: DocumentoSummary): string {
  if (enDominio(hostDe(doc.uri), "ted.europa.eu")) return "Anuncio publicado en TED";
  return TIPO_LABELS[doc.tipo] ?? doc.tipo;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

/** Enlace a la ficha del expediente en la plataforma de origen.
 *
 *  Es el único enlace estable que tenemos: `licitaciones.url` existe para el
 *  100% de las filas y no caduca, a diferencia de las URIs de los adjuntos. */
function EnlaceFicha({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-tf-meta text-primary hover:underline"
    >
      {children}
      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
      <AvisoPestanaNueva />
    </a>
  );
}

/** Bloque "Documentos" del detail panel: metadatos de los pliegos/adjuntos
 *  parseados por el scraper, con enlace a la fuente original (no se sirven
 *  copias propias — ver plan Pliegos+RAG en docs/IMPROVEMENT_BACKLOG.md).
 *
 *  Sobre `status === "error"`: se marca visualmente pero **el enlace se
 *  conserva**. `status` mezcla dos cosas distintas —el token de PLACSP caducó,
 *  o el fichero se descargó pero nuestro extractor no supo leerlo (.docx, .zip,
 *  escaneados sin OCR)— y en el segundo caso, que es aproximadamente uno de
 *  cada cuatro, el enlace abre perfectamente en el navegador. Romperlo sería
 *  peor que la nota de aviso. Por eso el bloque ofrece además la ficha del
 *  expediente (`fichaUrl`), que es la salida buena cuando el enlace directo ya
 *  no responde. */
export function DocumentosBlock({
  licitacionId,
  fichaUrl,
}: {
  licitacionId: string;
  /** Deeplink a la ficha del expediente (`licitacion.url`). Sin él el bloque
   *  mantiene el comportamiento anterior: si no hay documentos, no se pinta. */
  fichaUrl?: string | null;
}) {
  // Mismo hook que la ficha del expediente: compartían la clave
  // `["documentos", licitacionId]` con dos `queryFn` copiadas, que es la forma
  // en la que una de las dos deriva sin que nada avise.
  const { data } = useFactSheetDocumentos(licitacionId);

  const items: DocumentoSummary[] = data?.items ?? [];
  // F5.1: el documento que llegó después del primer lote se marca «Nuevo»
  // siete días — es el que avisó la campana, y aquí es donde se busca.
  const nuevos = documentosNuevos(items);

  if (items.length === 0) {
    if (!fichaUrl) return null;
    return (
      <div className="mt-6 space-y-2">
        <SectionTitle as="h3">Documentos</SectionTitle>
        <p className="text-tf-meta text-muted-foreground">
          No hemos indexado pliegos de este expediente. Pueden estar publicados en la ficha
          de la plataforma de contratación.
        </p>
        <EnlaceFicha href={fichaUrl}>{textosFicha(fichaUrl).ver}</EnlaceFicha>
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-3">
      <SectionTitle as="h3">Documentos</SectionTitle>
      <ul className="space-y-2">
        {items.map((doc) => {
          const caducado = doc.status === "error";
          return (
            <li key={doc.id} className="flex items-start gap-2">
              <FileText
                aria-hidden="true"
                className={cn("mt-0.5 h-4 w-4 shrink-0", caducado ? "text-muted-foreground/60" : "text-muted-foreground")}
              />
              <div className="min-w-0 flex-1">
                <a
                  href={doc.uri}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={cn(
                    "inline-flex items-center gap-1 break-all text-tf-body hover:underline",
                    caducado ? "text-muted-foreground" : "text-primary",
                  )}
                >
                  {doc.filename ?? etiquetaTipo(doc)}
                  <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
                  <AvisoPestanaNueva />
                </a>
                <p className="text-tf-meta text-muted-foreground">
                  {nuevos.has(doc.id) && (
                    <Badge variant="default" size="sm" className="mr-1.5">
                      Nuevo
                    </Badge>
                  )}
                  {etiquetaTipo(doc)}
                  {doc.size_bytes != null && ` · ${formatBytes(doc.size_bytes)}`}
                  {caducado && " · el enlace original puede haber caducado"}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
      {fichaUrl && <EnlaceFicha href={fichaUrl}>{textosFicha(fichaUrl).verTodos}</EnlaceFicha>}
    </div>
  );
}
