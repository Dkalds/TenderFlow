import type { Metadata } from "next";
import { headers } from "next/headers";
import { LiveRegion } from "@/components/live-region";
import { Providers } from "@/components/providers";
import { RouteProgress } from "@/components/route-progress";
import { Toaster } from "@/components/toaster";

export const metadata: Metadata = {
  title: "Restablecer contraseña",
  robots: { index: false, follow: false },
  alternates: { canonical: "/restablecer-contrasena" },
};

export default async function PasswordResetLayout({ children }: { children: React.ReactNode }) {
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
