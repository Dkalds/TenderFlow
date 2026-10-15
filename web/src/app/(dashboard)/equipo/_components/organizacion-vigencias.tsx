"use client";

/**
 * Vigencia de la documentación acreditativa, ordenada por la próxima caducidad.
 *
 * El estado y los días restantes los calcula el servidor
 * (`OrganizationCapabilitiesOut.vigencias`) con el mismo criterio que los
 * avisos de caducidad: aquí solo se pintan. Así la tarjeta no puede decir
 * «vigente» de un certificado del que la campana ya avisó que caduca.
 */

import { SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api-types";
import { formatDate } from "@/lib/utils";
import { TIPO_DOCUMENTO_LABELS } from "../_lib/etiquetas";

type Vigencia = Schemas["VigenciaDocumento"];
type Tono = "destructive" | "warning" | "success" | "neutral";

/** Qué se dice de cada estado, con su tono. */
export function estadoDeVigencia(vigencia: Vigencia): { texto: string; tono: Tono } {
  const dias = vigencia.dias_restantes;
  const fecha = formatDate(vigencia.vigente_hasta);
  switch (vigencia.estado) {
    case "caducado":
      return { texto: `Caducado el ${fecha}`, tono: "destructive" };
    case "caduca_pronto":
      if (dias === 0) return { texto: "Caduca hoy", tono: "warning" };
      if (dias === 1) return { texto: "Caduca mañana", tono: "warning" };
      return { texto: `Caduca en ${dias} días`, tono: "warning" };
    case "vigente":
      return { texto: `Vigente hasta el ${fecha}`, tono: "success" };
    case "sin_caducidad":
      return { texto: "Sin caducidad declarada", tono: "neutral" };
  }
}

export function OrganizacionVigencias({ vigencias }: { vigencias: Vigencia[] }) {
  if (vigencias.length === 0) return null;
  return (
    <section aria-labelledby="vigencia-documentacion" className="space-y-2">
      <div>
        <SectionTitle as="h3" id="vigencia-documentacion" className="mb-0.5">
          Vigencia de la documentación
        </SectionTitle>
        <p className="text-tf-meta text-muted-foreground">
          Por la próxima caducidad. El propietario y los administradores reciben un aviso a 60, 30 y 7 días y al
          caducar.
        </p>
      </div>
      <ul className="divide-y divide-border/60">
        {vigencias.map((vigencia) => {
          const { texto, tono } = estadoDeVigencia(vigencia);
          return (
            <li
              key={`${vigencia.tipo}-${vigencia.nombre}`}
              className="flex flex-wrap items-center justify-between gap-2 py-1.5"
            >
              <span className="min-w-0">
                <span className="block truncate text-tf-body text-foreground">{vigencia.nombre}</span>
                <span className="block text-tf-micro text-muted-foreground">
                  {TIPO_DOCUMENTO_LABELS[vigencia.tipo]}
                </span>
              </span>
              <Badge variant={tono} size="sm">
                {texto}
              </Badge>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
