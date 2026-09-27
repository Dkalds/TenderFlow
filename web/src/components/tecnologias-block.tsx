"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { ChevronRight, Cpu } from "lucide-react";
import { SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { tecnologiasKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

interface EvidenceRef {
  documento_id: number;
  page_number: number;
  quote: string;
  start_offset: number | null;
  end_offset: number | null;
}

interface TecnologiaDetalle {
  tecnologia: string;
  en_titulo: boolean;
  ml_probabilidad: number | null;
  ml_threshold_aplicado: number | null;
  pliego_keywords_score: number | null;
  pliego_keywords_terms: string[] | null;
  pliego_llm_score: number | null;
  pliego_llm_evidence: EvidenceRef[] | null;
}

interface TecnologiasResult {
  id_externo: string;
  items: TecnologiaDetalle[];
}

function origenes(item: TecnologiaDetalle): string[] {
  const result: string[] = [];
  if (item.en_titulo) result.push("título");
  if (item.ml_probabilidad != null) result.push("ML");
  if (item.pliego_keywords_score != null || item.pliego_llm_score != null) {
    result.push("pliego");
  }
  return result;
}

function hasEvidence(item: TecnologiaDetalle): boolean {
  return (
    (item.pliego_keywords_terms?.length ?? 0) > 0 || (item.pliego_llm_evidence?.length ?? 0) > 0
  );
}

function TecnologiaRow({ item }: { item: TecnologiaDetalle }) {
  const [expanded, setExpanded] = useState(false);
  const expandable = hasEvidence(item);

  return (
    <li className="rounded-md border border-border/60 px-3 py-2">
      <button
        type="button"
        onClick={() => expandable && setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 text-left disabled:cursor-default"
        disabled={!expandable}
        aria-expanded={expandable ? expanded : undefined}
      >
        <div className="flex min-w-0 items-center gap-2">
          <Cpu className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="truncate text-tf-body font-medium">{item.tecnologia}</span>
          <div className="flex shrink-0 gap-1">
            {origenes(item).map((o) => (
              <Badge key={o} size="sm">
                {o}
              </Badge>
            ))}
          </div>
        </div>
        {expandable && (
          // `rotate-90` escribe `rotate`, no `transform`: la transición nombra esa.
          <ChevronRight
            aria-hidden="true"
            className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-[rotate]", expanded && "rotate-90")}
          />
        )}
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5 pl-6 text-tf-meta text-muted-foreground">
          {item.pliego_keywords_terms && item.pliego_keywords_terms.length > 0 && (
            <p>Detectada en pliego por palabras clave: {item.pliego_keywords_terms.join(", ")}</p>
          )}
          {item.pliego_llm_evidence?.map((ev) => (
            <p key={`${ev.documento_id}-${ev.page_number}-${ev.quote}`}>
              Detectada en pliego (pág. {ev.page_number}): «{ev.quote}»
            </p>
          ))}
        </div>
      )}
    </li>
  );
}

/** Bloque "Tecnologías" del detail panel: consolida keyword-match de título,
 *  clasificador ML y señal detectada en el texto de los pliegos, con
 *  evidencia expandible (ver plan Pliegos+RAG en docs/IMPROVEMENT_BACKLOG.md).
 *  No se muestra cuando no hay ninguna tecnología detectada por ninguna
 *  fuente. (DocumentosBlock seguía este mismo criterio de `null` en vacío;
 *  desde que recibe `fichaUrl` ya no siempre: cuando la tiene, el vacío pasa a
 *  ser un enlace a la ficha del expediente. Aquí no hay equivalente — si no
 *  detectamos tecnologías, no hay ningún sitio al que mandar al usuario.) */
export function TecnologiasBlock({ licitacionId }: { licitacionId: string }) {
  const { data } = useQuery<TecnologiasResult>({
    queryKey: tecnologiasKeys.byLicitacion(licitacionId),
    queryFn: () =>
      fetchWithAuth(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/tecnologias`),
    staleTime: 5 * 60 * 1000,
  });

  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <div className="mt-6 space-y-3">
      <SectionTitle as="h3">Tecnologías</SectionTitle>
      <ul className="space-y-2">
        {items.map((item) => (
          <TecnologiaRow key={item.tecnologia} item={item} />
        ))}
      </ul>
    </div>
  );
}
