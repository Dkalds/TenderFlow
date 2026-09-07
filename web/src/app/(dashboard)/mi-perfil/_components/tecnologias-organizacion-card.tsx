"use client";

/**
 * Qué vende el equipo, y por tanto qué universo puntúa el Radar por defecto.
 *
 * Hasta 2026-09 las familias del diccionario eran literales en el código: un
 * partner de Microsoft o de Salesforce heredaba el corpus y el ranking
 * pensados para SAP, sin ninguna forma de decir lo contrario. Vacío sigue
 * significando «todas», que es el comportamiento anterior.
 *
 * La lista de familias válidas la manda el backend (`tecnologias_disponibles`):
 * mantenerla aquí a mano sería la lista paralela que el invariante 3 de
 * `web/AGENTS.md` prohíbe.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import {
  useOrganizationSettings,
  useUpdateOrganizationSettings,
} from "@/hooks/use-organization-settings";

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
    <Card>
      <CardHeader>
        <CardTitle>Tecnologías de tu organización</CardTitle>
        <CardDescription>
          El Radar acota su universo a estas familias cuando no filtras por tecnología a mano.
          Vacío significa todas.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando familias…</p>
        ) : disponibles.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No se pudieron cargar las familias del diccionario.
          </p>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {disponibles.map((familia) => (
              <label key={familia} className="flex items-center gap-2 text-sm">
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
          <p className="text-xs text-muted-foreground">
            Solo owner o admin pueden cambiarlas.
          </p>
        )}

        {puedeEditar && (
          <Button
            size="sm"
            disabled={!dirty || update.isPending}
            onClick={() =>
              update
                .mutateAsync(seleccion)
                .then(() => {
                  setDirty(false);
                  toast.success("Tecnologías guardadas. El Radar ya usa este ámbito.");
                })
                .catch((error: unknown) =>
                  toast.error(
                    error instanceof Error ? error.message : "No se pudieron guardar",
                  ),
                )
            }
          >
            Guardar tecnologías
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
