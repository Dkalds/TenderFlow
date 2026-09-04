"use client";

import { useFactSheetDocumentos } from "@/hooks/use-tender-fact-sheet";
import type { DocumentoSummary } from "@/lib/api-types";
import { ExternalLink, FileText } from "lucide-react";

const TIPO_LABELS: Record<string, string> = {
  legal: "Pliego administrativo (PCAP)",
  technical: "Pliego técnico (PPT)",
  additional: "Documento adicional",
};

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
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
    >
      {children}
      <ExternalLink className="h-3 w-3 shrink-0" />
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

  if (items.length === 0) {
    if (!fichaUrl) return null;
    return (
      <div className="mt-6 space-y-2">
        <h3 className="text-sm font-medium text-muted-foreground">Documentos</h3>
        <p className="text-xs text-muted-foreground">
          No hemos indexado pliegos de este expediente. Pueden estar publicados en la ficha
          de la plataforma de contratación.
        </p>
        <EnlaceFicha href={fichaUrl}>Ver en la ficha de PLACSP</EnlaceFicha>
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-3">
      <h3 className="text-sm font-medium text-muted-foreground">Documentos</h3>
      <ul className="space-y-2">
        {items.map((doc) => {
          const caducado = doc.status === "error";
          return (
            <li key={doc.id} className="flex items-start gap-2">
              <FileText
                className={`mt-0.5 h-4 w-4 shrink-0 ${
                  caducado ? "text-muted-foreground/60" : "text-muted-foreground"
                }`}
              />
              <div className="min-w-0 flex-1">
                <a
                  href={doc.uri}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`inline-flex items-center gap-1 text-sm hover:underline break-all ${
                    caducado ? "text-muted-foreground" : "text-primary"
                  }`}
                >
                  {doc.filename ?? TIPO_LABELS[doc.tipo] ?? doc.tipo}
                  <ExternalLink className="h-3 w-3 shrink-0" />
                </a>
                <p className="text-xs text-muted-foreground">
                  {TIPO_LABELS[doc.tipo] ?? doc.tipo}
                  {doc.size_bytes != null && ` · ${formatBytes(doc.size_bytes)}`}
                  {caducado && " · el enlace original puede haber caducado"}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
      {fichaUrl && <EnlaceFicha href={fichaUrl}>Ver todos en la ficha de PLACSP</EnlaceFicha>}
    </div>
  );
}
