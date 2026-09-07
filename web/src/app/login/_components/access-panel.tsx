"use client";

/**
 * Cuerpo normal de la tarjeta de acceso, en el orden en que se ofrece la
 * entrada: proveedor de identidad primero, cuenta local después.
 *
 * Es lo que se ve mientras no haya un gate de segundo factor pendiente; ese
 * caso lo cubre `MfaForm` y sustituye a esto entero.
 */

import { CONTACT_EMAIL, solicitarAccesoHref } from "@/lib/contacto";
import type { LoginForm } from "../_hooks/use-login-form";
import { CredentialsForm } from "./credentials-form";
import { DevLogin } from "./dev-login";
import { OAuthButtons } from "./oauth-buttons";
import { Separador } from "./separador";

export function AccessPanel({ login }: { login: LoginForm }) {
  return (
    <>
      {login.invitacion && (
        <div role="status" className="mb-4 rounded-md border border-dashed border-border bg-muted/30 p-3 text-sm">
          Tienes una invitación a un equipo de TenderFlow. Entra con el <strong>mismo correo</strong> al que se envió
          y te añadiremos automáticamente.
        </div>
      )}

      <OAuthButtons disabled={login.loading} onLogin={login.handleOAuthLogin} />

      <Separador etiqueta="o usa una cuenta local" />

      <div id="auth-panel" role="tabpanel" aria-labelledby={`tab-${login.mode}`}>
        <CredentialsForm login={login} />
      </div>

      {/* El alta self-service está desactivada en producción, así que quien
          llega desde la landing sin cuenta necesita saber por qué no puede
          entrar. La nota se enseña **siempre**: antes dependía de que el
          entorno definiera un email de contacto, de modo que justo en el
          despliegue peor configurado —el que manda el CTA a /login por no tener
          buzón— la pantalla no daba ninguna explicación. Con email, además,
          enlaza. */}
      <p className="text-muted-foreground mt-6 text-center text-xs leading-relaxed">
        El acceso es por invitación.{" "}
        {CONTACT_EMAIL ? (
          <a href={solicitarAccesoHref()} className="text-foreground font-medium underline-offset-4 hover:underline">
            Solicita acceso para tu equipo
          </a>
        ) : (
          <span>Se habilita tu email o el dominio de tu empresa.</span>
        )}
      </p>

      <DevLogin disabled={login.loading} onLogin={login.handleDevLogin} />
    </>
  );
}
