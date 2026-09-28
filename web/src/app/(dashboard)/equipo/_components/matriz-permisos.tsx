"use client";

/**
 * Matriz de permisos por rol sobre los espacios de la consola.
 *
 * Los cuatro roles eran una etiqueta junto al nombre: sabías que alguien era
 * «viewer» y no qué podía hacer. La matriz responde la pregunta que de verdad
 * se hace quien invita a alguien — a qué le está dando acceso.
 *
 * Es documentación de la política que aplica el backend, no la política: lo que
 * manda son sus comprobaciones de permisos.
 *
 * Salió de `page.tsx` en el troceado de S7 (allowlist de `max-lines`).
 */

import { Check } from "lucide-react";
import { Panel, PanelTitle } from "@/components/console/panel";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { ROLE_LABELS } from "../_lib/etiquetas";

const ROLES = ["owner", "admin", "member", "viewer"] as const;
type Role = (typeof ROLES)[number];

const PERMISSIONS: { capability: string; detail: string; roles: Role[] }[] = [
  { capability: "Ver los espacios de análisis", detail: "Radar, Mercado, Competencia", roles: ["owner", "admin", "member", "viewer"] },
  { capability: "Guardar vistas y reglas propias", detail: "Mi Watchlist, Mi perfil", roles: ["owner", "admin", "member"] },
  { capability: "Abrir y editar oportunidades", detail: "decisión, responsable, precio", roles: ["owner", "admin", "member"] },
  { capability: "Declarar NIF y capacidad", detail: "pestaña Organización", roles: ["owner", "admin"] },
  { capability: "Invitar y quitar miembros", detail: "Equipo", roles: ["owner", "admin"] },
  { capability: "Cambiar el rol de otros", detail: "Equipo", roles: ["owner"] },
  { capability: "Ops y administración", detail: "cola de errores, claves de API, feature flags", roles: ["owner"] },
];

export function MatrizPermisos() {
  return (
    <Panel>
      <PanelTitle title="Qué puede hacer cada rol" hint="resumen orientativo: cada acción comprueba su permiso" />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-tf-meta">
          <thead>
            <tr className="border-b border-border/60">
              <th scope="col" className={cn("px-2 py-2 text-left", CABECERA_COLUMNA)}>
                Capacidad
              </th>
              {ROLES.map((role) => (
                <th key={role} scope="col" className={cn("w-24 px-2 py-2 text-center", CABECERA_COLUMNA)}>
                  {ROLE_LABELS[role]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERMISSIONS.map((permission) => (
              <tr key={permission.capability} className="border-b border-border/40 last:border-b-0">
                <td className="px-2 py-2">
                  <div className="text-tf-body font-medium">{permission.capability}</div>
                  <div className="text-tf-micro text-muted-foreground">{permission.detail}</div>
                </td>
                {ROLES.map((role) => {
                  const allowed = permission.roles.includes(role);
                  return (
                    <td key={role} className="px-2 py-2 text-center">
                      <span className="sr-only">{allowed ? "Permitido" : "No permitido"}</span>
                      {allowed ? (
                        <Check className="mx-auto h-3.5 w-3.5 text-success" aria-hidden="true" />
                      ) : (
                        <span className="text-muted-foreground" aria-hidden="true">
                          ·
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
