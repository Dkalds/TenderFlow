"use client";

/**
 * Qué vende el equipo, y por tanto qué universo puntúa el Radar por defecto.
 *
 * Hasta 2026-09 las familias del diccionario eran literales en el código: un
 * partner de Microsoft o de Salesforce heredaba el universo y el ranking
 * pensados para SAP, sin ninguna forma de decir lo contrario. Vacío sigue
 * significando «todas», que es el comportamiento anterior.
 *
 * La lista de familias válidas la manda el backend (`tecnologias_disponibles`):
 * mantenerla aquí a mano sería la lista paralela que el invariante 3 de
 * `web/AGENTS.md` prohíbe.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import {
  useOrganizationSettings,
  useUpdateOrganizationSettings,
} from "@/hooks/use-organization-settings";
import { getErrorMessage } from "@/lib/query-feedback";

export function TecnologiasOrganizacionCard() {
  const activeOrganizationId = useActiveOrganizationId();
  const organizations = useOrganizations();
  const { data, isLoading } = useOrganizationSettings(activeOrganizationId);
  const update = useUpdateOrganizationSettings(activeOrganizationId);

  const [seleccion, setSeleccion] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    setSeleccion(data.tecnologias ?? []); // eslint-disable-line react-hooks/set-state-in-effect
    setDirty(false);
  }, [data]);

  const rol = organizations.data?.find((o) => o.id === activeOrganizationId)?.role;
  const puedeEditar = rol === "owner" || rol === "admin";
  const disponibles = data?.tecnologias_disponibles ?? [];

  const alternar = (familia: string) => {
    setSeleccion((previa) =>
      previa.includes(familia) ? previa.filter((f) => f !== familia) : [...previa, familia],
    );
    setDirty(true);
  };

  return (
    <Panel>
      <PanelTitle title="Tecnologías de tu organización" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        El Radar acota su universo a estas familias cuando no filtras por tecnología a mano. Vacío significa todas.
      </p>
      <div className="space-y-3">
        {isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : disponibles.length === 0 ? (
          <p className="text-tf-meta text-muted-foreground">No se pudieron cargar las familias de tecnología.</p>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {disponibles.map((familia) => (
              <label key={familia} className="flex items-center gap-2 text-tf-body">
                <Checkbox
                  checked={seleccion.includes(familia)}
                  disabled={!puedeEditar}
                  onCheckedChange={() => alternar(familia)}
                  aria-label={familia}
                />
                {familia}
              </label>
            ))}
          </div>
        )}

        {!puedeEditar && !isLoading && (
          <p className="text-tf-meta text-muted-foreground">
            Solo un propietario o un administrador puede cambiarlas.
          </p>
        )}

        {puedeEditar && (
          <Button
            size="sm"
            disabled={!dirty || update.isPending}
            onClick={() =>
              update
                .mutateAsync({ tecnologias: seleccion })
                .then(() => {
                  setDirty(false);
                  toast.success("Tecnologías guardadas. El Radar ya usa este ámbito.");
                })
                .catch((error: unknown) => toast.error(getErrorMessage(error, "accion")))
            }
          >
            Guardar tecnologías
          </Button>
        )}
      </div>
    </Panel>
  );
}
