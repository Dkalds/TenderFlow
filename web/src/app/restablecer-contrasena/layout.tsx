import type { Metadata } from "next";
import { SuperficiePrivada } from "@/components/layout/superficie-privada";

export const metadata: Metadata = {
  title: "Restablecer contraseña",
  robots: { index: false, follow: false },
  alternates: { canonical: "/restablecer-contrasena" },
};

/** Providers, `Toaster` y nonce: la pila común de `SuperficiePrivada`. */
export default function PasswordResetLayout({ children }: { children: React.ReactNode }) {
  return <SuperficiePrivada>{children}</SuperficiePrivada>;
}
