"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { ExternalLink, FileText } from "lucide-react";

interface Documento {
  id: number;
  tipo: string;
  uri: string;
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  status: string;
  created_at: string | null;
}

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

/** Bloque "Documentos" del detail panel: metadatos de los pliegos/adjuntos
 *  parseados por el scraper, con enlace a la fuente original (no se sirven
 *  copias propias — ver plan Pliegos+RAG en docs/IMPROVEMENT_BACKLOG.md). */
export function DocumentosBlock({ licitacionId }: { licitacionId: string }) {
  const { data } = useQuery<{ items: Documento[] }>({
    queryKey: ["documentos", licitacionId],
    queryFn: () =>
      fetchWithAuth(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/documentos`),
    staleTime: 5 * 60 * 1000,
  });

  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <div className="mt-6 space-y-3">
      <h3 className="text-sm font-medium text-muted-foreground">Documentos</h3>
      <ul className="space-y-2">
        {items.map((doc) => (
          <li key={doc.id} className="flex items-start gap-2">
            <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <a
                href={doc.uri}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline break-all"
              >
                {doc.filename ?? TIPO_LABELS[doc.tipo] ?? doc.tipo}
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
              <p className="text-xs text-muted-foreground">
                {TIPO_LABELS[doc.tipo] ?? doc.tipo}
                {doc.size_bytes != null && ` · ${formatBytes(doc.size_bytes)}`}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
