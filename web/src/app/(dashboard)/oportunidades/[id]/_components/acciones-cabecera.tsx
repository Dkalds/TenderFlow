"use client";

import Link from "next/link";
import { Download, MessageSquareText, X } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { useAsistente } from "@/lib/asistente-store";
import { triggerDownload } from "@/lib/export";

/** Lo que las acciones necesitan de la oportunidad. */
interface PursuitCabecera {
  id: number | string;
  licitacion_id: string;
  tender_title?: string | null;
}

/**
 * Las acciones de la cabecera de una oportunidad: el one-pager para dirección,
 * preguntar a la IA sobre su expediente, abrirlo en Detalle y cerrar la ficha.
 *
 * «Preguntar a la IA» llegó en 2026-10 con el asistente único: lo abre con el
 * expediente de la oportunidad como contexto —con su resumen a un clic—, el
 * mismo asistente y la misma conversación que se abren desde la ficha de
 * Detalle, sin salir de la pantalla donde se decide.
 */
export function AccionesCabecera({ pursuit }: { pursuit: PursuitCabecera }) {
  const abrirAsistente = useAsistente((s) => s.abrir);
  const preguntar = () =>
    abrirAsistente({
      contexto: {
        expedientes: [
          { id: pursuit.licitacion_id, titulo: pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}` },
        ],
        origen: "oportunidad",
      },
    });

  return (
    <div className="flex flex-none flex-wrap items-center gap-2">
      {/* F2.7 — el one-pager para dirección. La API lo servía desde
          `GET /pursuits/{id}/ficha.pdf` y ninguna pantalla lo pedía. */}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void triggerDownload(`/api/v1/pursuits/${pursuit.id}/ficha.pdf`)}
      >
        <Download aria-hidden="true" />
        Descargar PDF
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={preguntar}>
        <MessageSquareText aria-hidden="true" />
        Preguntar a la IA
      </Button>
      {/* Destino de TenderFlow: sin icono de «salir». */}
      <Link
        href={`/detalle?lic=${encodeURIComponent(pursuit.licitacion_id)}`}
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        Ver en Detalle
      </Link>
      {/* `ml-auto`: bajo el título, el cierre queda en el extremo derecho
          de la fila; al lado del título el margen no mueve nada. */}
      <Link
        href="/oportunidades"
        aria-label="Cerrar la ficha"
        className={buttonVariants({
          variant: "ghost",
          size: "icon-sm",
          className: "text-muted-foreground ml-auto flex-none",
        })}
      >
        <X aria-hidden="true" />
      </Link>
    </div>
  );
}
