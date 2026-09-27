"use client";

/**
 * Puerta de entrada al producto.
 *
 * Aquí solo queda el armazón: la carcasa de la puerta
 * (`(publico)/_components/puerta.tsx`, la misma de restablecer contraseña y del
 * 404 raíz) y la decisión de qué cuerpo se monta en su panel —la sesión ya
 * abierta, el gate de segundo factor o el panel de acceso normal—. Los cinco
 * caminos de entrada y sus errores viven en `_hooks/use-login-form.ts`, y cada
 * bloque del panel en `_components/`.
 *
 * La composición es la de la portada (decisión D4, 2026-09-26): texto a la
 * izquierda, formulario en un panel sólido a la derecha y el logo enlazado a
 * `/`. El fondo animado de partículas, la retícula, el halo y la tarjeta de
 * cristal centrada se fueron con ella; el porqué, en `puerta.tsx`.
 */

import { Suspense } from "react";
import { Puerta } from "@/app/(publico)/_components/puerta";
import { useSession } from "@/lib/auth";
import { AccessPanel } from "./_components/access-panel";
import { ALTA_ABIERTA, AuthModeTabs } from "./_components/auth-mode-tabs";
import { MfaForm } from "./_components/mfa-form";
import { SesionAbierta } from "./_components/sesion-abierta";
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
  const { user, isLoading } = useSession();

  // Con la sesión ya abierta no se vuelve a pedir la contraseña (F55), salvo
  // que la URL traiga algo que solo resuelve el formulario: una invitación
  // (se canjea al entrar), un error del callback o el gate del segundo factor.
  // `/auth/me` responde 200 también a una sesión con el segundo factor
  // pendiente y no dice si ya se verificó, así que a las cuentas con MFA se les
  // sigue enseñando el formulario, como antes; mientras `/auth/me` no ha
  // contestado, también.
  const conMfa = user !== null && "mfa_required" in user && user.mfa_required === true;
  const sesionAbierta =
    !isLoading && user !== null && !conMfa && !login.mfaPending && !login.invitacion && !login.error;

  let panel: React.ReactNode;
  if (sesionAbierta && user) {
    panel = <SesionAbierta email={user.email} destino={login.destino} onCambiarCuenta={login.cerrarSesion} />;
  } else if (login.mfaPending) {
    panel = <MfaForm login={login} />;
  } else {
    panel = (
      <>
        {ALTA_ABIERTA && <AuthModeTabs mode={login.mode} onChange={login.switchMode} />}
        <AccessPanel login={login} />
      </>
    );
  }

  // Sin "tiempo real" en el lede: la ingesta es cada cuatro horas y el propio
  // FAQ de la portada lo dice; el copy público no promete lo que el producto no
  // hace.
  return (
    <Puerta titulo="Entra en TenderFlow" lede="El radar de licitaciones TI del sector público español." panel={panel} />
  );
}
