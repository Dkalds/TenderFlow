"use client";

/**
 * Ámbito del perfil: privado o compartido con la organización.
 *
 * Un perfil compartido es el que usan los miembros que no tienen uno propio; el
 * badge de «heredado» dice cuándo lo que se está viendo viene de ahí.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

export function AmbitoPerfilCard({
  inherited,
  shared,
  onSharedChange,
}: {
  inherited: boolean;
  shared: boolean;
  onSharedChange: (checked: boolean) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ámbito del perfil</CardTitle>
        <CardDescription>
          El Radar usa el perfil del ámbito activo. Un perfil compartido sirve como
          referencia para los miembros que no tengan uno propio.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {inherited && <Badge variant="secondary">Perfil heredado de la organización</Badge>}
        <div className="flex items-center justify-between gap-4">
          <label htmlFor="profile-visibility" className="space-y-1">
            <span className="block text-sm font-medium">Compartir con la organización</span>
            <span className="block text-xs text-muted-foreground">
              Los demás miembros podrán usar estos pesos si no han creado un perfil propio.
            </span>
          </label>
          <Switch
            id="profile-visibility"
            checked={shared}
            onCheckedChange={onSharedChange}
            aria-label="Compartir perfil con la organización"
          />
        </div>
      </CardContent>
    </Card>
  );
}
