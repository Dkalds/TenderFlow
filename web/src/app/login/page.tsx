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

import { lazy, Suspense } from "react";
import { Puerta } from "@/app/(publico)/_components/puerta";
import { useSession } from "@/lib/auth";
import { AccessPanel } from "./_components/access-panel";
import { ALTA_ABIERTA, AuthModeTabs } from "./_components/auth-mode-tabs";
import { useLoginForm } from "./_hooks/use-login-form";

// Las dos ramas que casi nadie ve al llegar —el gate del segundo factor y la
// sesión ya abierta— se cargan cuando hacen falta: `/login` tiene techo en
// `bundle-budget.json` y el primer render solo necesita el formulario.
// `React.lazy` y no `next/dynamic`, que añade a esta ruta su propio cargador
// (medido: +2,5 KB, más de lo que ahorra).
const MfaForm = lazy(() => import("./_components/mfa-form").then((m) => ({ default: m.MfaForm })));
const SesionAbierta = lazy(() =>
  import("./_components/sesion-abierta").then((m) => ({ default: m.SesionAbierta })),
);

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

  // Cada rama perezosa lleva su propio `Suspense`: sin él suspendería el de
  // toda la página y la puerta entera parpadearía mientras llega el trozo.
  let panel: React.ReactNode;
  if (sesionAbierta && user) {
    panel = (
      <Suspense fallback={null}>
        <SesionAbierta email={user.email} destino={login.destino} onCambiarCuenta={login.cerrarSesion} />
      </Suspense>
    );
  } else if (login.mfaPending) {
    panel = (
      <Suspense fallback={null}>
        <MfaForm login={login} />
      </Suspense>
    );
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
