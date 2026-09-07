"use client";

/**
 * Gate del segundo factor.
 *
 * Sustituye al formulario de acceso, no lo acompaña: llegado aquí la sesión ya
 * existe pero está *pendiente*, y el backend responde 403 a todo lo que no sea
 * `/auth/me`, `/auth/logout` y `/auth/totp/verify`. Por eso «Cancelar» revoca
 * la sesión en vez de limitarse a volver atrás.
 */

import { AlertCircle, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { LoginForm } from "../_hooks/use-login-form";

export function MfaForm({ login }: { login: LoginForm }) {
  const { error, loading, mfaCode } = login;

  return (
    <form onSubmit={login.handleVerifyMfa} className="space-y-4">
      {error && (
        <div
          id="mfa-error"
          role="alert"
          aria-live="polite"
          className="animate-in fade-in-0 slide-in-from-bottom-2 bg-destructive/10 text-destructive flex items-center gap-2 rounded-md p-3 text-sm"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="space-y-2">
        <label htmlFor="mfa-code" className="text-foreground text-sm font-medium">
          Código de verificación
        </label>
        <Input
          id="mfa-code"
          type="text"
          inputMode="numeric"
          placeholder="123456"
          value={mfaCode}
          onChange={(e) => login.setMfaCode(e.target.value)}
          required
          autoComplete="one-time-code"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "mfa-hint mfa-error" : "mfa-hint"}
          disabled={loading}
        />
        <p id="mfa-hint" className="text-muted-foreground text-xs">
          Introduce el código de seis dígitos de tu app de autenticación. También puedes usar uno de tus códigos de
          recuperación.
        </p>
      </div>

      <Button type="submit" className="w-full" disabled={loading || !mfaCode.trim()}>
        <ShieldCheck className="mr-2 h-4 w-4" />
        {loading ? "Cargando…" : "Verificar"}
      </Button>

      <Button
        type="button"
        variant="ghost"
        className="w-full"
        disabled={loading}
        onClick={() => void login.cancelarMfa()}
      >
        Cancelar y volver
      </Button>
    </form>
  );
}
