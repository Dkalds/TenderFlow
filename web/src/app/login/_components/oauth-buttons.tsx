"use client";

/**
 * Entrada por proveedor de identidad — el acceso recomendado.
 *
 * Va antes que el formulario local a propósito: es el camino que menos falla y
 * el único que no exige recordar una contraseña. Hay un E2E que comprueba ese
 * orden en el DOM (`e2e/login.spec.ts`).
 */

import { Button } from "@/components/ui/button";

/**
 * ¿Se ofrece el botón de Microsoft?
 *
 * El backend solo lo sirve si `OAUTH_MICROSOFT_CLIENT_ID` está configurado
 * (si no, `/auth/oauth/microsoft/authorize` responde 501). Enseñar el botón en
 * un despliegue sin configurar sería exactamente la superficie que promete lo
 * que el backend no hace, así que se gobierna con la misma bandera de entorno
 * que ya usa la pestaña de alta.
 */
export const MICROSOFT_HABILITADO =
  process.env.NEXT_PUBLIC_OAUTH_MICROSOFT === "1" || process.env.NODE_ENV === "development";

export function OAuthButtons({
  disabled,
  onLogin,
}: {
  disabled: boolean;
  onLogin: (provider: "google" | "microsoft", nombre: string) => Promise<void>;
}) {
  return (
    <>
      <p className="mb-2 text-xs font-medium text-muted-foreground">Acceso recomendado</p>
      <Button
        variant="outline"
        className="w-full"
        onClick={() => void onLogin("google", "Google")}
        disabled={disabled}
      >
        <svg aria-hidden="true" className="mr-2 h-4 w-4" viewBox="0 0 24 24">
          <path
            d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
            fill="#4285F4"
          />
          <path
            d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
            fill="#34A853"
          />
          <path
            d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
            fill="#FBBC05"
          />
          <path
            d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
            fill="#EA4335"
          />
        </svg>
        Continuar con Google
      </Button>

      {MICROSOFT_HABILITADO && (
        <Button
          variant="outline"
          className="mt-2 w-full"
          onClick={() => void onLogin("microsoft", "Microsoft")}
          disabled={disabled}
        >
          {/* Logo de Microsoft: los cuatro cuadrados de su marca. */}
          <svg aria-hidden="true" className="mr-2 h-4 w-4" viewBox="0 0 23 23">
            <path d="M1 1h10v10H1z" fill="#F25022" />
            <path d="M12 1h10v10H12z" fill="#7FBA00" />
            <path d="M1 12h10v10H1z" fill="#00A4EF" />
            <path d="M12 12h10v10H12z" fill="#FFB900" />
          </svg>
          Continuar con Microsoft
        </Button>
      )}
    </>
  );
}
