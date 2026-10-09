/**
 * Lo que ve quien no es propietario ni administrador. El permiso lo decide el
 * backend (403 en `/pursuits/direccion` y `/pursuits/direccion/carga`); esto
 * sólo lo dice, en todas las vistas del espacio con la misma frase.
 */
import { Panel, PanelEmpty } from "@/components/console/panel";
import { ICONO_ADMIN } from "@/lib/iconos";

export function SinPermisoDireccion() {
  return (
    <Panel>
      <PanelEmpty
        icon={ICONO_ADMIN}
        title="Dirección es solo para propietarios y administradores"
        hint="Tu rol en esta organización no permite ver este espacio."
      />
    </Panel>
  );
}
