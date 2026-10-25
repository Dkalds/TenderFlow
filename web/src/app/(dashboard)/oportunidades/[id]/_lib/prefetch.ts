import { organizationKeys } from "@/lib/claves-raiz";
import type { ConsultaServidor } from "@/lib/server-prefetch";

/**
 * Lo que `oportunidades/[id]/page.tsx` pide en servidor: el listado de
 * organizaciones de quien mira (`GET /organizations`).
 *
 * Es poco, y no por descuido. Todo lo que pinta la ficha —el pursuit, el
 * contraste del pliego, el kit, la matriz go/no-go, las etiquetas y los
 * miembros— va con `organization_id` de la organización activa, que vive en
 * `localStorage` y el servidor no ve (`lib/server-prefetch.ts`, regla 2): una
 * sola de esas consultas hidratada con la organización por defecto le daría a
 * quien eligió otra un HTML distinto del de su primer render.
 *
 * El listado de organizaciones no depende de ella, y es justo el primer
 * eslabón de la cascada de la ficha: sin una organización recordada en el
 * navegador —la primera carga de cada sesión, porque el login la olvida— la
 * ficha no sabe con qué organización pedir el pursuit hasta que contesta
 * `/organizations`. Llegando hidratado, el pursuit y lo que precarga
 * `precarga-ficha.tsx` salen sin esperar ese viaje.
 *
 * El test de `oportunidades/[id]/_lib/__tests__/prefetch.test.tsx` monta
 * `useOrganizations` y comprueba que cachea bajo esta clave y pide esta ruta.
 */
export function consultasFicha(): ConsultaServidor[] {
  return [{ queryKey: organizationKeys.all, path: "/api/v1/organizations" }];
}
