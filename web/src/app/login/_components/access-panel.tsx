"use client";

/**
 * Cuerpo normal del panel de acceso, en el orden en que se ofrece la entrada:
 * proveedor de identidad primero, correo y contraseña después.
 *
 * Es lo que se ve mientras no haya un gate de segundo factor pendiente ni una
 * sesión ya abierta; esos casos los cubren `MfaForm` y `SesionAbierta`, que
 * sustituyen a esto entero.
 */

import { Aviso } from "@/components/console/aviso";
import { solicitarAccesoHref } from "@/lib/contacto";
import type { LoginForm } from "../_hooks/use-login-form";
import { CredentialsForm } from "./credentials-form";
import { DevLogin } from "./dev-login";
import { OAuthButtons } from "./oauth-buttons";
import { Separador } from "./separador";

export function AccessPanel({ login }: { login: LoginForm }) {
  return (
    <>
      {login.invitacion && (
        <Aviso tone="info" className="mb-5">
          Tienes una invitación a un equipo de TenderFlow. Entra con el <strong>mismo correo</strong> al que se envió y
          te añadiremos automáticamente.
        </Aviso>
      )}

      <OAuthButtons disabled={login.loading} onLogin={login.handleOAuthLogin} />

      <Separador etiqueta="o con correo y contraseña" />

      {/* El panel de las pestañas «Iniciar sesión / Crear cuenta», que se
          enseñan siempre (`auth-mode-tabs.tsx`). */}
      <div id="auth-panel" role="tabpanel" aria-labelledby={`tab-${login.mode}`}>
        <CredentialsForm login={login} />
      </div>

      {/* Quien llega desde la landing sin acceso necesita saber por qué no
          puede entrar. La nota siempre enlaza: el destino es el formulario de
          la portada (`lib/contacto`), que no depende de ninguna variable de
          entorno. En el alta no sale: el propio formulario ya dice que hace
          falta el acceso concedido, con el mismo enlace. */}
      {!login.isRegister && (
        <p className="text-muted-foreground text-tf-meta mt-6 leading-relaxed">
          El acceso es por invitación.{" "}
          <a
            href={solicitarAccesoHref()}
            className="text-foreground focus-visible:ring-ring rounded-sm font-medium underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:outline-none"
          >
            Solicita acceso para tu equipo
          </a>
        </p>
      )}

      <DevLogin disabled={login.loading} onLogin={login.handleDevLogin} />
    </>
  );
}
