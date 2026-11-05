"use client";

import type * as React from "react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import { ChevronRight, Cpu } from "lucide-react";
import { PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { tecnologiasKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

type TecnologiaDetalle = Schemas["TecnologiaDetalle"];
type TecnologiasResult = ApiGetResult<"/api/v1/licitaciones/{id_externo}/tecnologias">;

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
    <li className="rounded-md border border-divider px-3 py-2">
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
 *
 *  Carga, fallo y vacío se distinguen: hasta 2026-11 los tres devolvían
 *  `null`, así que una API caída se leía como «no hay tecnología detectada».
 *  `conTitulo={false}` cuando el contenedor ya rotula la sección (la ficha de
 *  la oportunidad la llama «Señal tecnológica»). */
export function TecnologiasBlock({ licitacionId, conTitulo = true }: { licitacionId: string; conTitulo?: boolean }) {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: tecnologiasKeys.byLicitacion(licitacionId),
    queryFn: () =>
      fetchWithAuth<TecnologiasResult>(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/tecnologias`),
    staleTime: 5 * 60 * 1000,
    // El fallo se pinta aquí mismo (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const items = data?.items ?? [];
  let cuerpo: React.ReactNode;
  if (isPending) {
    cuerpo = (
      <div className="space-y-2" aria-hidden="true">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-2/3" />
      </div>
    );
  } else if (error) {
    cuerpo = (
      <PanelError
        variant="inline"
        className="py-0"
        title="No se pudo cargar la señal tecnológica"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  } else if (items.length === 0) {
    cuerpo = (
      <PanelEmpty
        size="sm"
        className="py-0"
        title="Sin tecnología detectada"
        hint="Ni el título, ni el clasificador, ni el texto de los pliegos apuntan a una tecnología concreta."
      />
    );
  } else {
    cuerpo = (
      <ul className="space-y-2">
        {items.map((item) => (
          <TecnologiaRow key={item.tecnologia} item={item} />
        ))}
      </ul>
    );
  }

  return (
    <div className={cn("space-y-3", conTitulo && "mt-6")} aria-busy={isPending || undefined}>
      {conTitulo && <SectionTitle as="h3">Tecnologías</SectionTitle>}
      {cuerpo}
    </div>
  );
}
