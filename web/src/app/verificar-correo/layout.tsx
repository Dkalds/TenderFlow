import type { Metadata } from "next";
import { SuperficiePrivada } from "@/components/layout/superficie-privada";

export const metadata: Metadata = {
  title: "Activar la cuenta",
  robots: { index: false, follow: false },
};

/**
 * Providers, `Toaster` y nonce: la pila común de `SuperficiePrivada`, como
 * `/restablecer-contrasena`. Es superficie de credenciales —el enlace abre
 * sesión—, así que conserva la CSP estricta con nonce (`lib/rutas-publicas.ts`
 * la declara no prerenderizada).
 */
export default function VerificarCorreoLayout({ children }: { children: React.ReactNode }) {
  return <SuperficiePrivada>{children}</SuperficiePrivada>;
}
