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
import { errorDeRespuesta } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { authKeys } from "@/lib/claves-raiz";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

/**
 * Lo que devuelve `GET /auth/me`. `mfa_required` dice si la cuenta tiene la
 * verificación en dos pasos activa; se calcula en cada petición, así que tras
 * activarla o quitarla basta con `refresh()`.
 */
export type AuthUser = Schemas["UserInfo"];

const RUTA_ME = "/api/v1/auth/me";

interface SessionContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /**
   * `/auth/me` falló por algo que no es «sin sesión» (5xx, red) y se agotaron
   * los reintentos. No significa que no haya sesión: quien redirige a /login
   * tiene que mirar esto antes.
   */
  error: unknown;
  refresh: () => Promise<void>;
}

/**
 * La sesión del servidor, o `null` si no la hay. Solo 401 y 403 son «sin
 * sesión»; cualquier otro fallo se lanza para que React Query lo reintente con
 * la política global (`debeReintentar`) en vez de echar al usuario a /login
 * porque la API tardó en despertar.
 */
export async function pedirSesion(signal?: AbortSignal): Promise<AuthUser | null> {
  const res = await fetch(RUTA_ME, { credentials: "include", signal });
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) throw await errorDeRespuesta(res, "GET", RUTA_ME);
  return (await res.json()) as AuthUser;
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

  // Sin `retry` propio: hereda `debeReintentar` del QueryClient. El fallo no
  // lanza toast; lo pinta en línea quien depende de la sesión (`AdminGuard`).
  const { data, isLoading, error } = useQuery<AuthUser | null>({
    queryKey: authKeys.me,
    queryFn: ({ signal }) => pedirSesion(signal),
    staleTime: 10 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
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
      isAdmin: data?.is_admin === true,
      error,
      refresh,
    }),
    [data, isLoading, error, refresh],
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
