"use client";

/**
 * Administración — DLQ, usuarios, claves API y webhooks.
 *
 * Vista compartida por la ruta `/administracion` y por `?vista=administracion`
 * del espacio Ops. La guarda de administrador viaja **con la vista**, no con el
 * layout de la ruta: cuando vivía en `administracion/layout.tsx`, montar el
 * cuerpo desde `/ops` la saltaba entera y las consultas de admin salían igual
 * para un usuario sin permisos. Envuelve al componente, no a su JSX, para que
 * los `useQuery` de `/admin/users` no lleguen a dispararse — por eso cada
 * tarjeta pide sus propios datos: nada de esto se monta fuera de la guarda.
 */

import { Separator } from "@/components/ui/separator";
import { AdminGuard } from "@/components/admin-guard";
import { SolicitudesAccesoCard } from "./solicitudes-acceso-card";
import { ApiKeysCard } from "./administracion/api-keys-card";
import { DlqCard } from "./administracion/dlq-card";
import { UsuariosCard } from "./administracion/usuarios-card";
import { WebhooksCard } from "./administracion/webhooks-card";

export default function AdministracionView() {
  return (
    <AdminGuard>
      <AdministracionContent />
    </AdminGuard>
  );
}

function AdministracionContent() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Administración</h1>
        <p className="text-muted-foreground">Gestión de DLQ, usuarios y claves API.</p>
      </div>

      {/* Cola de solicitudes de acceso llegadas desde la landing pública. Va
          primero porque es lo único de esta pantalla con trabajo pendiente
          esperando a una persona. */}
      <SolicitudesAccesoCard />

      <DlqCard />

      <Separator />

      <UsuariosCard />

      <ApiKeysCard />

      <Separator />

      <WebhooksCard />
    </div>
  );
}
