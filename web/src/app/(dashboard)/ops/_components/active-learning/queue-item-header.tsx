"use client";

/**
 * Cabecera de una tarjeta de la cola: título (enlazado al origen cuando lo
 * hay), expediente, los metadatos como badges y la descripción colapsable.
 */

import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { QueueItem } from "../../_hooks/use-active-learning";

export function QueueItemHeader({
  item,
  descExpanded,
  onToggleDesc,
}: {
  item: QueueItem;
  descExpanded: boolean;
  onToggleDesc: () => void;
}) {
  return (
    <>
      <div>
        <div className="flex items-start gap-2">
          <p className="font-medium leading-snug flex-1">
            {item.url_origen ? (
              <a
                href={item.url_origen}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline"
              >
                {item.titulo ?? "Sin título"}
                <ExternalLink className="inline h-3 w-3 ml-1 text-muted-foreground" />
              </a>
            ) : (
              item.titulo ?? "Sin título"
            )}
          </p>
        </div>
        <p className="text-xs text-muted-foreground font-mono mt-0.5">
          {item.id_externo}
        </p>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {item.organo && (
            <Badge variant="outline" className="text-xs">
              {item.organo}
            </Badge>
          )}
          {item.ccaa && (
            <Badge variant="outline" className="text-xs">
              {item.ccaa}
            </Badge>
          )}
          {item.cpv && (
            <Badge variant="secondary" className="text-xs font-mono">
              CPV {item.cpv}
            </Badge>
          )}
          {item.importe != null && (
            <Badge variant="outline" className="text-xs">
              {formatCurrency(item.importe)}
            </Badge>
          )}
          {item.fecha_publicacion && (
            <Badge variant="outline" className="text-xs">
              {formatDate(item.fecha_publicacion)}
            </Badge>
          )}
          {item.tecnologia && (
            <Badge variant="outline" className="text-xs border-blue-300 text-blue-700 dark:text-blue-400 dark:border-blue-700">
              {item.tecnologia}
            </Badge>
          )}
        </div>
      </div>

      {item.descripcion && (
        <div>
          <button
            type="button"
            className="text-xs text-muted-foreground hover:underline flex items-center gap-1"
            onClick={onToggleDesc}
          >
            {descExpanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            {descExpanded ? "Ocultar descripción" : "Ver descripción"}
          </button>
          {descExpanded && (
            <p className="text-sm text-muted-foreground mt-1 whitespace-pre-line">
              {item.descripcion}
            </p>
          )}
        </div>
      )}
    </>
  );
}
