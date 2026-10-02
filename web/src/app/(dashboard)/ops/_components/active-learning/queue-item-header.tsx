"use client";

/**
 * Cabecera de una tarjeta de la cola: título (enlazado al origen cuando lo
 * hay), expediente, los metadatos como badges y la descripción colapsable.
 */

import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { QueueItem } from "../../_lib/active-learning";

export function QueueItemHeader({
  item,
  descExpanded,
  onToggleDesc,
}: {
  item: QueueItem;
  descExpanded: boolean;
  onToggleDesc: () => void;
}) {
  const idDescripcion = `descripcion-${item.id_externo}`;
  return (
    <>
      <div>
        <p className="text-tf-body font-medium leading-snug">
          {item.url_origen ? (
            <a href={item.url_origen} target="_blank" rel="noopener noreferrer" className="hover:underline">
              {item.titulo ?? "Sin título"}
              <ExternalLink className="ml-1 inline h-3 w-3 text-muted-foreground" aria-hidden="true" />
              <AvisoPestanaNueva />
            </a>
          ) : (
            (item.titulo ?? "Sin título")
          )}
        </p>
        <p className="mt-0.5 font-mono text-tf-meta text-muted-foreground">{item.id_externo}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.organo && (
            <Badge variant="outline" size="sm">
              {item.organo}
            </Badge>
          )}
          {item.ccaa && (
            <Badge variant="outline" size="sm">
              {item.ccaa}
            </Badge>
          )}
          {item.cpv && (
            <Badge variant="secondary" size="sm" className="font-mono">
              CPV {item.cpv}
            </Badge>
          )}
          {item.importe != null && (
            <Badge variant="outline" size="sm">
              {formatCurrency(item.importe)}
            </Badge>
          )}
          {item.fecha_publicacion && (
            <Badge variant="outline" size="sm">
              {formatDate(item.fecha_publicacion)}
            </Badge>
          )}
          {item.tecnologia && (
            <Badge variant="info" size="sm">
              {item.tecnologia}
            </Badge>
          )}
        </div>
      </div>

      {item.descripcion && (
        <div>
          <button
            type="button"
            className="flex items-center gap-1 rounded-sm text-tf-meta text-muted-foreground hover:text-foreground"
            onClick={onToggleDesc}
            aria-expanded={descExpanded}
            aria-controls={descExpanded ? idDescripcion : undefined}
          >
            {descExpanded ? "Ocultar descripción" : "Ver descripción"}
            {descExpanded ? (
              <ChevronUp className="h-3 w-3" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-3 w-3" aria-hidden="true" />
            )}
          </button>
          {descExpanded && (
            <p id={idDescripcion} className="mt-1 whitespace-pre-line text-tf-body text-muted-foreground">
              {item.descripcion}
            </p>
          )}
        </div>
      )}
    </>
  );
}
