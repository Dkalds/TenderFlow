"use client";

/**
 * Una familia del checklist go/no-go y los requisitos que la componen (S2.3).
 *
 * Todo lo que se pinta aquí viene resuelto del backend: el veredicto, el motivo
 * en castellano, la cita del pliego y el dato de la organización que se usó
 * (`services/go_no_go.py`). Este componente no compara nada ni completa huecos
 * — sólo hay una regla propia, y es defensiva: **un `cumple` sin cita no se
 * pinta como cumplido**. El backend garantiza que no lo emite; si un día
 * llegara, se degrada a «desconocido» diciendo por qué, que es exactamente lo
 * que el módulo de dominio hace con ese caso.
 */

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type {
  ChecklistFamiliaResultado,
  ChecklistItem,
  ChecklistVeredicto,
} from "@/hooks/use-pursuit-checklist";
import type { DocumentoSummary } from "@/lib/api-types";

const VEREDICTO_BADGE: Record<
  ChecklistVeredicto,
  { label: string; variant: "success" | "destructive" | "secondary" }
> = {
  cumple: { label: "Cumple", variant: "success" },
  no_cumple: { label: "No cumple", variant: "destructive" },
  desconocido: { label: "Desconocido", variant: "secondary" },
};

const SIN_CITA =
  "Llegó marcado como cumplido pero sin ninguna cita del pliego que lo respalde, " +
  "así que no se presenta como cumplido.";

/** El veredicto que se puede defender con lo que trae el propio ítem. */
export function veredictoDeItem(item: ChecklistItem): ChecklistVeredicto {
  if (item.veredicto === "cumple" && (item.evidencia ?? []).length === 0) return "desconocido";
  return item.veredicto;
}

/**
 * El peor veredicto de la familia, con la misma degradación aplicada.
 *
 * No es una agregación nueva: el backend ya manda `familia.veredicto` y es el
 * que se usa. Sólo se baja a «desconocido» cuando alguno de sus ítems se ha
 * degradado, para que la cabecera no diga «Cumple» encima de un requisito que
 * el detalle presenta como no verificado.
 */
function veredictoDeFamilia(familia: ChecklistFamiliaResultado): ChecklistVeredicto {
  const items = familia.items ?? [];
  if (familia.veredicto === "cumple" && items.some((item) => veredictoDeItem(item) !== "cumple")) {
    return "desconocido";
  }
  return familia.veredicto;
}

function VeredictoBadge({ veredicto }: { veredicto: ChecklistVeredicto }) {
  const badge = VEREDICTO_BADGE[veredicto];
  return (
    <Badge variant={badge.variant} className="flex-none">
      {badge.label}
    </Badge>
  );
}

/** Etiqueta y enlace de una cita, resueltos contra los metadatos del documento. */
function citaPresentation(
  documentoId: number,
  pageNumber: number,
  docsById: Map<number, DocumentoSummary>,
): { label: string; href: string | null } {
  const doc = docsById.get(documentoId);
  if (!doc) return { label: `Documento ${documentoId} · página ${pageNumber}`, href: null };
  return {
    label: `${doc.filename ?? doc.tipo} · página ${pageNumber}`,
    href: doc.uri ? `${doc.uri}#page=${pageNumber}` : null,
  };
}

function ChecklistItemRow({
  item,
  docsById,
}: {
  item: ChecklistItem;
  docsById: Map<number, DocumentoSummary>;
}) {
  const veredicto = veredictoDeItem(item);
  const evidencia = item.evidencia ?? [];
  const degradado = veredicto !== item.veredicto;
  // Sin dato de la organización no se puede contrastar: lo que falta está de
  // nuestro lado de la mesa, y el sitio de rellenarlo es el perfil de capacidad.
  const faltaDatoPropio = veredicto === "desconocido" && !item.dato_organizacion;

  return (
    <li className="rounded-lg border border-border/60 bg-background/40 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 text-[12.5px] font-medium leading-snug">{item.requisito}</p>
        <VeredictoBadge veredicto={veredicto} />
      </div>

      <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
        {degradado ? SIN_CITA : item.motivo}
      </p>

      <p className="mt-1.5 text-[11.5px] leading-relaxed">
        <span className="text-muted-foreground">Dato de la organización: </span>
        {item.dato_organizacion ? (
          <span className="font-medium">{item.dato_organizacion}</span>
        ) : (
          <span className="text-muted-foreground">sin declarar</span>
        )}
      </p>

      {faltaDatoPropio && (
        <Link
          href="/equipo"
          className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-medium text-primary hover:underline"
        >
          Completar el perfil de capacidad (Equipo → Organización)
        </Link>
      )}

      {evidencia.length > 0 ? (
        <details className="mt-2 text-[11.5px]">
          <summary className="cursor-pointer font-medium text-primary hover:underline">
            {evidencia.length} cita{evidencia.length === 1 ? "" : "s"} del pliego
          </summary>
          <ul className="mt-2 space-y-2 border-l-2 border-primary/25 pl-3">
            {evidencia.map((cita, index) => {
              const fuente = citaPresentation(cita.documento_id, cita.page_number, docsById);
              return (
                <li key={`${cita.documento_id}-${cita.page_number}-${index}`}>
                  {fuente.href ? (
                    <a
                      href={fuente.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                    >
                      {fuente.label}
                      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
                    </a>
                  ) : (
                    <p className="font-medium text-muted-foreground">{fuente.label}</p>
                  )}
                  <blockquote className="mt-1 leading-relaxed text-foreground/85">
                    «{cita.quote}»
                  </blockquote>
                </li>
              );
            })}
          </ul>
        </details>
      ) : (
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground/85">
          Sin cita del pliego para este requisito.
        </p>
      )}
    </li>
  );
}

export function ChecklistFamilia({
  familia,
  docsById,
}: {
  familia: ChecklistFamiliaResultado;
  docsById: Map<number, DocumentoSummary>;
}) {
  const items = familia.items ?? [];
  const veredicto = veredictoDeFamilia(familia);

  return (
    // Abierta de entrada: lo que hay que ver es *por qué* una familia dice lo
    // que dice, y esconderlo tras un clic convierte el panel en cuatro
    // etiquetas de colores. `open` es constante, así que React no vuelve a
    // tocar el atributo y plegarla a mano se respeta. Las citas del pliego sí
    // van plegadas, como en la pestaña Pliego.
    <details open className="rounded-[10px] border border-border/60 bg-card/40 px-3 py-2.5">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2.5">
        <span className="min-w-0 flex-1 text-[12.5px] font-semibold">{familia.etiqueta}</span>
        <span className="tf-tnum flex-none text-[10.5px] text-muted-foreground">
          {items.length} requisito{items.length === 1 ? "" : "s"}
        </span>
        <VeredictoBadge veredicto={veredicto} />
      </summary>
      <ul className="mt-2.5 space-y-2">
        {items.map((item, index) => (
          <ChecklistItemRow key={`${item.requisito}-${index}`} item={item} docsById={docsById} />
        ))}
      </ul>
    </details>
  );
}
