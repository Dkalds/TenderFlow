import { headers } from "next/headers";
import { LiveRegion } from "@/components/live-region";
import { Providers } from "@/components/providers";
import { RouteProgress } from "@/components/route-progress";
import { Toaster } from "@/components/toaster";

/**
 * El envoltorio común de la superficie con sesión: dashboard, `/login` y
 * `/restablecer-contrasena` (S5.9 del plan de septiembre, S7.1 del v2).
 *
 * Los tres layouts montaban a mano la misma pila —leer el nonce, `Providers`,
 * `RouteProgress`, `Toaster`, `LiveRegion`— y ya habían divergido una vez: un
 * `toast()` disparado en `/login` se perdía en silencio porque el `Toaster`
 * sólo existía en el dashboard. Ahora esa pila se declara aquí y los tres
 * layouts la usan; lo que cada uno añade (el marco de consola, la paleta, el
 * copiloto…) va como `children`.
 *
 * **Por qué no es un grupo de rutas `(privado)`**, que es lo que pedía el plan:
 * un layout sólo envuelve a sus descendientes en el árbol de ficheros, así que
 * tener uno común exigía mover `(dashboard)/` entero —cientos de ficheros y los
 * imports `@/app/(dashboard)/…` de sus tests— debajo del grupo nuevo. El
 * intento anterior (§8 del plan de septiembre) se revirtió a medio mover. Y lo
 * que un layout común habría comprado de verdad, conservar el `QueryClient` y
 * el `Toaster` al cruzar entre superficies, apenas se da: entrar y salir de la
 * sesión son navegaciones completas (`window.location` en
 * `login/_hooks/use-login-form.ts`), que remontan todo igual. Con un
 * componente se consigue lo que sí importaba —una sola definición, imposible
 * que diverja— sin mover un fichero.
 *
 * Lee `headers()` para el nonce de la CSP estricta (`src/proxy.ts`), que es lo
 * que obliga a que las tres rutas sean dinámicas; la superficie pública no
 * pasa por aquí y conserva su prerender.
 */
export async function SuperficiePrivada({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <Providers nonce={nonce}>
      <RouteProgress />
      {children}
      <Toaster />
      <LiveRegion />
    </Providers>
  );
}
