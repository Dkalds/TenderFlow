"use client";

/**
 * Citas de documentos propios de la organización (ADR-040).
 *
 * Son extractos **literales** de adjuntos que alguien del equipo permitió
 * citar, no texto generado: por eso van aparte de la respuesta del asistente y
 * de los puntos del guion, rotulados, con el fichero, la página y la
 * oportunidad de la que salen. Quien los lee puede abrir el fichero y
 * comprobarlo; la descarga es la de siempre, por enlace firmado que caduca.
 *
 * Lo usan el hilo del asistente (`chat-thread.tsx`) y el guion de la oferta
 * (`pliego/guion-oferta.tsx`).
 */
import Link from "next/link";
import { useDescargarAdjunto } from "@/hooks/use-pursuit-adjuntos";
import type { CitaOrganizacion } from "@/lib/api-types";

export function CitasOrganizacion({ citas }: { citas: CitaOrganizacion[] }) {
  const descargar = useDescargarAdjunto();
  if (citas.length === 0) return null;
  return (
    <div className="mt-2 space-y-1">
      <p className="text-tf-meta font-medium text-muted-foreground">
        De documentos de tu organización ({citas.length})
      </p>
      {citas.map((cita) => (
        <blockquote
          key={`${cita.attachment_id}-${cita.page_number ?? "s"}`}
          className="border-l-2 border-border pl-2 text-tf-meta text-muted-foreground"
        >
          <span className="break-words font-medium text-foreground">
            {cita.filename}
            {cita.page_number != null ? `, p. ${cita.page_number}` : ""}
          </span>
          <span className="block">{cita.cita}</span>
          <span className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
            <Link
              href={`/oportunidades/${cita.pursuit_id}`}
              className="font-medium text-primary hover:underline"
            >
              Oportunidad: {cita.licitacion_titulo ?? cita.licitacion_id}
            </Link>
            <button
              type="button"
              disabled={descargar.isPending}
              aria-label={`Descargar ${cita.filename}`}
              onClick={() => descargar.mutate({ id: cita.attachment_id, filename: cita.filename })}
              className="font-medium text-primary hover:underline disabled:opacity-50"
            >
              Descargar el fichero
            </button>
          </span>
        </blockquote>
      ))}
    </div>
  );
}
