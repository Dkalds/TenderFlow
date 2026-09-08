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
import { ROLE_LABELS } from "../_lib/etiquetas";

const ROLES = ["owner", "admin", "member", "viewer"] as const;
type Role = (typeof ROLES)[number];

const PERMISSIONS: { capability: string; detail: string; roles: Role[] }[] = [
  { capability: "Ver los espacios de análisis", detail: "Radar, Mercado, Competencia", roles: ["owner", "admin", "member", "viewer"] },
  { capability: "Guardar vistas y watchlists propias", detail: "Mi Watchlist, Mi perfil de scoring", roles: ["owner", "admin", "member"] },
  { capability: "Abrir y editar oportunidades", detail: "decisión, responsable, precio", roles: ["owner", "admin", "member"] },
  { capability: "Declarar NIF y capacidad", detail: "pestaña Organización", roles: ["owner", "admin"] },
  { capability: "Invitar y quitar miembros", detail: "Equipo", roles: ["owner", "admin"] },
  { capability: "Cambiar el rol de otros", detail: "Equipo", roles: ["owner"] },
  { capability: "Ops y administración", detail: "DLQ, claves API, feature flags", roles: ["owner"] },
];

export function MatrizPermisos() {
  return (
    <Panel>
      <PanelTitle
        title="Qué puede hacer cada rol"
        hint="documenta la política que aplica el backend"
      />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-border/70">
              <th scope="col" className="px-2 py-2 text-left font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                Capacidad
              </th>
              {ROLES.map((role) => (
                <th
                  key={role}
                  scope="col"
                  className="w-24 px-2 py-2 text-center font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                >
                  {ROLE_LABELS[role]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERMISSIONS.map((permission) => (
              <tr key={permission.capability} className="border-b border-border/25">
                <td className="px-2 py-2">
                  <div className="font-medium">{permission.capability}</div>
                  <div className="text-[10.5px] text-muted-foreground">{permission.detail}</div>
                </td>
                {ROLES.map((role) => {
                  const allowed = permission.roles.includes(role);
                  return (
                    <td key={role} className="px-2 py-2 text-center">
                      <span className="sr-only">{allowed ? "Permitido" : "No permitido"}</span>
                      {allowed ? (
                        <Check className="mx-auto h-3.5 w-3.5 text-[hsl(var(--success))]" aria-hidden="true" />
                      ) : (
                        <span className="text-muted-foreground/40" aria-hidden="true">
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
