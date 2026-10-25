/**
 * `QueryClient` de los tests con el aviso global de mutaciones montado.
 *
 * Un `new QueryClient()` a secas no lleva la `MutationCache` de
 * `components/providers.tsx`, así que en una prueba el fallo de una mutación
 * no avisa. Eso empujaba a repetir el `toast.error` en el componente para
 * poder asertarlo, y en la aplicación el mismo fallo salía dos veces (D6 en
 * docs/UX_AUDIT.md). Con este cliente la prueba ve el aviso que ve el usuario,
 * con el `meta.errorTitle` de la mutación.
 *
 * Las consultas y mutaciones van sin reintentos: un test no espera backoffs.
 */
import { QueryClient } from "@tanstack/react-query";

import { crearMutationCache } from "@/lib/query-feedback";

export function crearQueryClientDePrueba(): QueryClient {
  return new QueryClient({
    mutationCache: crearMutationCache(),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}
