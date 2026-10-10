"use client";

/**
 * Ámbito del perfil: privado o compartido con la organización.
 *
 * Un perfil compartido es el que usan los miembros que no tienen uno propio.
 * Que lo que se está viendo viene de ahí lo dice la página arriba del todo,
 * antes del primer campo, y no esta tarjeta, que queda al final.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { AYUDA_CAMPO, ETIQUETA_CAMPO } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";

export function AmbitoPerfilCard({
  shared,
  onSharedChange,
}: {
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
