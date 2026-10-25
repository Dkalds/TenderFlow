import { headers } from "next/headers";
import { LiveRegion } from "@/components/live-region";
import { Providers } from "@/components/providers";
import { Toaster } from "@/components/toaster";

/**
 * El envoltorio común de la superficie con sesión: dashboard, `/login`,
 * `/restablecer-contrasena` y `/verificar-correo` (S5.9 del plan de
 * septiembre, S7.1 del v2).
 *
 * Los tres layouts montaban a mano la misma pila —leer el nonce, `Providers`,
 * `Toaster`, `LiveRegion`— y ya habían divergido una vez: un
 * `toast()` disparado en `/login` se perdía en silencio porque el `Toaster`
 * sólo existía en el dashboard. Ahora esa pila se declara aquí y los tres
 * layouts la usan; lo que cada uno añade (el marco de consola, la paleta, el
 * asistente…) va como `children`.
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
      {children}
      <Toaster />
      <LiveRegion />
      {process.env.NODE_ENV === "development" && nonce ? (
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: CARGADOR_LIVE_IMPECCABLE }} />
      ) : null}
    </Providers>
  );
}

/**
 * Solo en desarrollo: deja cargar el selector del modo live de impeccable en
 * las superficies con nonce.
 *
 * `impeccable live` inyecta en el layout raíz un `<script src>` hacia
 * `localhost:8400` sin nonce. En la superficie pública basta con la excepción
 * de host de la CSP; aquí rige `'strict-dynamic'`, que ignora los hosts y
 * bloquea ese script. Lo que `'strict-dynamic'` sí deja pasar es un script
 * creado desde otro que lleva el nonce, así que este, con el nonce, busca el
 * bloqueado y lo vuelve a crear. Sin live arrancado no encuentra nada.
 */
const ORIGEN_LIVE_IMPECCABLE = "http://localhost:8400"; // fdi-allow:localhost-url — helper de desarrollo, no dato renderizado

const CARGADOR_LIVE_IMPECCABLE = `document.addEventListener("DOMContentLoaded", function () {
  var bloqueado = document.querySelector('script[src^="${ORIGEN_LIVE_IMPECCABLE}/live.js"]');
  if (!bloqueado) return;
  var script = document.createElement("script");
  script.src = bloqueado.src;
  document.body.appendChild(script);
});`;
