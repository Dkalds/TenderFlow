"use client";

/**
 * Qué familias puntúa el Radar por decisión de la organización, en una línea.
 *
 * Elegirlas es un ajuste del equipo y vive en Equipo › Organización. Aquí se
 * dejan a la vista porque acotan el universo sobre el que actúa todo lo demás
 * de esta página: unos pesos impecables no encuentran licitaciones de una
 * tecnología que la organización dejó fuera.
 */

import { EnlaceIr } from "@/components/console/panel";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { useOrganizationSettings } from "@/hooks/use-organization-settings";

export function AmbitoOrganizacion() {
  const organizationId = useActiveOrganizationId();
  const { data } = useOrganizationSettings(organizationId);
  // Sin el dato no se afirma nada: «todas las tecnologías» es una respuesta,
  // no lo que se dice mientras se carga o cuando falla.
  const tecnologias = data?.tecnologias;
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-tf-meta text-muted-foreground">
      {tecnologias && (
        <span>
          {tecnologias.length > 0 ? (
            <>
              Tu organización puntúa solo{" "}
              <span className="font-medium text-foreground">{tecnologias.join(", ")}</span>.
            </>
          ) : (
            "Tu organización puntúa todas las tecnologías."
          )}
        </span>
      )}
      <EnlaceIr href="/equipo">Tecnologías e informe semanal, en Equipo › Organización</EnlaceIr>
    </p>
  );
}
