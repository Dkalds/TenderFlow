"use client";

/**
 * Administración — quién entra, quién puede qué y qué está encendido.
 *
 * Vista compartida por la ruta `/administracion` y por `?vista=administracion`
 * del espacio Ops. La guarda de administrador viaja **con la vista**, no con el
 * layout de la ruta: cuando vivía en `administracion/layout.tsx`, montar el
 * cuerpo desde `/ops` la saltaba entera y las consultas de admin salían igual
 * para un usuario sin permisos. Envuelve al componente, no a su JSX, para que
 * los `useQuery` de `/admin/users` no lleguen a dispararse — por eso cada
 * tarjeta pide sus propios datos: nada de esto se monta fuera de la guarda.
 *
 * Reagrupación 2026-10: absorbe lo que eran dos vistas propias —Feature flags
 * (una fila en producción) y Webhooks (ninguna)— y suelta lo que no era suyo:
 *
 * - La **cola de errores** se fue a Ejecuciones, con el resto de lo que falla.
 * - Las **claves de API** que había aquí eran las del propio administrador,
 *   rotuladas como «de la instancia», leídas con una forma que la API no
 *   devuelve y con un botón que respondía siempre 400. La pantalla que funciona
 *   está en Ajustes; aquí queda el camino.
 * - La tarjeta de **webhooks** con alta y borrado operaba sobre la organización
 *   de quien la miraba: era Equipo › Integraciones con otro título. Queda la
 *   lista global de la instancia, que es lo que solo se puede ver desde aquí.
 *
 * `ancla` desplaza la pantalla a una de sus secciones: es lo que hace que un
 * marcador de `/feature-flags` o de `?vista=webhooks` siga aterrizando donde
 * está lo que buscaba.
 */

import * as React from "react";
import { EnlaceIr, Panel, PanelTitle } from "@/components/console/panel";
import { Separator } from "@/components/ui/separator";
import { AdminGuard } from "@/components/admin-guard";
import { SolicitudesAccesoCard } from "./solicitudes-acceso-card";
import { FeatureFlagsCard } from "./administracion/feature-flags-card";
import { UsuariosCard } from "./administracion/usuarios-card";
import { WebhooksGlobales } from "./webhooks-view";

/**
 * `ancla` es el `id` de una de sus secciones (`feature-flags`, `webhooks`): los
 * declara `VISTAS_FUSIONADAS` y un test comprueba que cada uno existe en el
 * código que lo pinta.
 */
export default function AdministracionView({ ancla }: { ancla?: string }) {
  return (
    <AdminGuard>
      <AdministracionContent ancla={ancla} />
    </AdminGuard>
  );
}

function AdministracionContent({ ancla }: { ancla?: string }) {
  React.useEffect(() => {
    if (!ancla) return;
    // Opcional: jsdom no implementa `scrollIntoView`.
    document.getElementById(ancla)?.scrollIntoView?.({ block: "start" });
  }, [ancla]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Administración</h1>
        <p className="text-tf-meta text-muted-foreground">
          Solicitudes de acceso, usuarios, feature flags y webhooks de la instancia.
        </p>
      </div>

      {/* Cola de solicitudes de acceso llegadas desde la landing pública. Va
          primero porque es lo único de esta pantalla con trabajo pendiente
          esperando a una persona. */}
      <SolicitudesAccesoCard />

      <UsuariosCard />

      <Panel>
        <PanelTitle as="h2" title="Claves de API" />
        <p className="mb-2 max-w-prose text-tf-meta text-muted-foreground">
          Cada persona crea, rota y revoca las suyas. Desactivar a un usuario revoca las que tuviera.
        </p>
        <EnlaceIr href="/ajustes?vista=claves">Tus claves, en Ajustes</EnlaceIr>
      </Panel>

      <Separator />

      <FeatureFlagsCard />

      <WebhooksGlobales />
    </div>
  );
}
