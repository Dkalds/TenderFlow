/**
 * Sesión del usuario: `SessionProvider` pide `/api/v1/auth/me` al montar, lo
 * guarda en React Query y `useSession()` lo entrega en todo el árbol.
 *
 * El contexto lleva un almacén que no cambia nunca, no la sesión; ver
 * `SessionProvider` para el porqué.
 */
"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { authKeys } from "@/lib/claves-raiz";

export interface AuthUser {
  user_id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  role?: string;
}

interface SessionContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  refresh: () => Promise<void>;
}

/**
 * La sesión fuera del valor del contexto: `useSession` se suscribe con
 * `useSyncExternalStore`. `inicial` es la sesión del primer render del
 * proveedor —la que pintó el servidor— y es la instantánea de servidor con la
 * que se hidrata cada consumidor, llegue cuando llegue.
 */
interface AlmacenSesion {
  suscribir: (aviso: () => void) => () => void;
  actual: () => SessionContextValue;
  inicial: () => SessionContextValue;
  publicar: (sesion: SessionContextValue) => void;
}

function crearAlmacen(primera: SessionContextValue): AlmacenSesion {
  let vigente = primera;
  const avisos = new Set<() => void>();
  return {
    suscribir(aviso) {
      avisos.add(aviso);
      return () => {
        avisos.delete(aviso);
      };
    },
    actual: () => vigente,
    inicial: () => primera,
    publicar(sesion) {
      if (sesion === vigente) return;
      vigente = sesion;
      for (const aviso of avisos) aviso();
    },
  };
}

const SessionContext = React.createContext<AlmacenSesion | null>(null);

/**
 * Pide la sesión y la pone al alcance de `useSession()`.
 *
 * **El valor del contexto no cambia nunca**, y no es un detalle. Las pantallas
 * con prefetch en servidor (`web/AGENTS.md`) llegan en streaming: primero el
 * marco con el esqueleto de `loading.tsx` y, al acabar el prefetch, el cuerpo
 * de la vista en un `<div hidden id="S:n">`. El runtime de React no lo revela
 * en el acto: lo deja en cola (`$~`) hasta el siguiente frame o hasta 300 ms
 * después de la revelación anterior, y React no puede hidratar un límite en
 * cola. Cuando la sesión iba en el valor del contexto, la respuesta de
 * `/auth/me` —que llega justo después de hidratar— alcanzaba a ese límite y
 * React tiraba su HTML y lo pintaba de nuevo en el cliente, con la copia del
 * servidor todavía oculta en el DOM: la pantalla entera dos veces y sus IDs
 * duplicados hasta que corría la revelación (con la pestaña en segundo plano,
 * no hasta volver a ella). Se veía en /resumen, cuyo prefetch tarda lo
 * bastante para que su cuerpo llegue en una revelación aparte.
 *
 * Ahora el cambio de sesión sólo re-renderiza a quien la lee, cada uno por su
 * suscripción, y los límites pendientes se hidratan con el HTML del servidor
 * cuando se revelan. Lo fija `lib/__tests__/auth-streaming.test.tsx`.
 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<AuthUser | null>({
    queryKey: authKeys.me,
    queryFn: async () => {
      try {
        const res = await fetch("/api/v1/auth/me", { credentials: "include" });
        if (!res.ok) return null;
        return res.json() as Promise<AuthUser>;
      } catch {
        return null;
      }
    },
    staleTime: 10 * 60 * 1000,
    retry: false,
  });

  const refresh = React.useCallback(async () => {
    // Invalidar la key fija reejecuta la query montada; ya no hace falta un
    // contador en la queryKey (que dejaba entradas de caché muertas).
    await queryClient.invalidateQueries({ queryKey: authKeys.me });
  }, [queryClient]);

  const sesion = React.useMemo(
    () => ({
      user: data ?? null,
      isLoading,
      isAuthenticated: data !== null && data !== undefined,
      isAdmin: data?.is_admin === true || data?.role === "admin",
      refresh,
    }),
    [data, isLoading, refresh],
  );

  const [almacen] = React.useState(() => crearAlmacen(sesion));
  React.useEffect(() => {
    almacen.publicar(sesion);
  }, [almacen, sesion]);

  return <SessionContext.Provider value={almacen}>{children}</SessionContext.Provider>;
}

/**
 * Hook to access the current session.
 * Must be used within a SessionProvider.
 */
export function useSession(): SessionContextValue {
  const almacen = React.useContext(SessionContext);
  if (!almacen) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return React.useSyncExternalStore(almacen.suscribir, almacen.actual, almacen.inicial);
}
