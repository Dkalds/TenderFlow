"use client";

/**
 * Puerta de entrada al producto.
 *
 * Aquí solo queda el armazón: fondo, tarjeta y la decisión de qué cuerpo se
 * monta —el gate de segundo factor o el panel de acceso normal—. Los cinco
 * caminos de entrada y sus errores viven en `_hooks/use-login-form.ts`, y cada
 * bloque de la tarjeta en `_components/`. Ningún texto, ningún estado de error
 * y ningún flujo cambió al repartirlos.
 */

import { Suspense } from "react";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { ParticleField } from "@/components/layout/particle-field";
import { AccessPanel } from "./_components/access-panel";
import { ALTA_ABIERTA, AuthModeTabs } from "./_components/auth-mode-tabs";
import { MfaForm } from "./_components/mfa-form";
import { useLoginForm } from "./_hooks/use-login-form";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginPageContent />
    </Suspense>
  );
}

function LoginPageContent() {
  const login = useLoginForm();

  return (
    <div className="bg-background relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      {/* Animated particle backdrop, sobre la misma retícula fina que el hero
          de la landing: la puerta de entrada y la portada comparten fondo. */}
      <div aria-hidden="true" className="tf-hero-grid absolute inset-0 z-0" />
      <ParticleField className="z-0" />
      {/* Soft radial halo to calm the area behind the card and keep contrast */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-0 [background:radial-gradient(closest-side,hsl(var(--background)/0.85),transparent_70%)]"
      />

      {/* Landmark `main` con el mismo id que en el dashboard: el skip link del
          layout raíz se renderiza en todas las rutas y aquí apuntaba a un
          ancla inexistente. */}
      <main id="main-content" tabIndex={-1} className="relative z-10 w-full max-w-md space-y-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <TenderFlowLogo showText={false} boxSize={48} />
          <div>
            <h1 className="tf-display text-foreground">TenderFlow</h1>
            {/* Sin "tiempo real": la ingesta es cada cuatro horas y el propio
                FAQ de la landing lo dice — el copy público no promete lo que
                el producto no hace. */}
            <p className="text-muted-foreground mt-1 text-sm">Radar de licitaciones TI del sector público español</p>
          </div>
        </div>

        {/* Rare, first-load-only screen: the only place a delight-tier
            entrance is warranted (find-animation-opportunities — occasional
            frequency, "delight" purpose). */}
        <Card className="border-border/70 animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-200 shadow-xl backdrop-blur-sm">
          <CardHeader className="space-y-4">
            {ALTA_ABIERTA && <AuthModeTabs mode={login.mode} onChange={login.switchMode} />}
            <CardDescription>
              {login.isRegister
                ? "Crea tu cuenta con correo y contraseña"
                : "Accede con tu cuenta para ver el dashboard"}
            </CardDescription>
          </CardHeader>

          <CardContent>
            {login.mfaPending ? <MfaForm login={login} /> : <AccessPanel login={login} />}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
