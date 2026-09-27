"use client";

/**
 * Ámbito del perfil: privado o compartido con la organización.
 *
 * Un perfil compartido es el que usan los miembros que no tienen uno propio; el
 * badge de «heredado» dice cuándo lo que se está viendo viene de ahí.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { AYUDA_CAMPO, ETIQUETA_CAMPO } from "@/components/ui/field";
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
    <Panel>
      <PanelTitle title="Ámbito del perfil" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        El Radar usa el perfil del ámbito activo. Un perfil compartido sirve de referencia a los miembros que no
        tengan uno propio.
      </p>
      <div className="space-y-3">
        {inherited && <Badge variant="secondary">Perfil heredado de la organización</Badge>}
        <div className="flex items-center justify-between gap-4">
          <label htmlFor="profile-visibility" className="space-y-1">
            <span className={ETIQUETA_CAMPO}>Compartir con la organización</span>
            <span className={`block ${AYUDA_CAMPO}`}>
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
      </div>
    </Panel>
  );
}
