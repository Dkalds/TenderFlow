/**
 * Claves de React Query que necesita código que viaja en **todas** las rutas,
 * `/login` incluida: `lib/auth.tsx` (la sesión) y `components/providers.tsx`
 * (la política de refresco por prefijo). Las de `hooks/use-organization.ts`
 * llegaron por lo mismo; ese módulo ya no viaja en el login —lo único que la
 * pantalla de acceso usa de él está en `lib/organization-store.ts`—, pero sus
 * claves siguen aquí.
 *
 * Importaban de `lib/query-keys.ts`, y Turbopack no recorta los exports que no
 * se usan de un módulo: el registro entero viajaba en el First Load del login,
 * así que cada clave nueva de cualquier pantalla lo engordaba hasta romper su
 * techo (`web/bundle-budget.json`). Le pasó a `master` el 2026-10-09.
 *
 * `query-keys.ts` reexporta `authKeys` y `organizationKeys` y reutiliza los dos prefijos de
 * pursuits: el registro sigue completo (lo comprueba
 * `lib/__tests__/query-keys.test.ts`) y cada prefijo sigue siendo uno. Aquí no
 * entra nada que sólo use una pantalla.
 */
export const authKeys = {
  all: ["auth"] as const,
  me: ["auth", "me"] as const,
};

export const PURSUITS_RAIZ = ["pursuits"] as const;
export const PURSUITS_AGENDA = ["pursuits", "agenda"] as const;

/** Organización de una clave con ámbito: `undefined` es «todavía no se sabe». */
type OrganizacionDeClave = number | null | undefined;

export const organizationKeys = {
  all: ["organizations"] as const,
  members: (organizationId: OrganizacionDeClave) => ["organization-members", organizationId] as const,
  settings: (organizationId: OrganizacionDeClave) => ["organization-settings", organizationId] as const,
  /**
   * Plantilla de tareas por etapa (F4.6). Nace bajo la raíz, no con literal
   * propio como `members`/`settings`: no hay clientes desplegados que migrar.
   */
  plantillaTareas: (organizationId: OrganizacionDeClave) =>
    ["organizations", "plantilla-tareas", organizationId] as const,
};
