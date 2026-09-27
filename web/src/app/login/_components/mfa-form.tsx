"use client";

/**
 * Gate del segundo factor.
 *
 * Sustituye al formulario de acceso, no lo acompaña: llegado aquí la sesión ya
 * existe pero está *pendiente*, y el backend responde 403 a todo lo que no sea
 * `/auth/me`, `/auth/logout` y `/auth/totp/verify`. Por eso «Cancelar» revoca
 * la sesión en vez de limitarse a volver atrás.
 */

import { ShieldCheck } from "lucide-react";
import { Aviso } from "@/components/console/aviso";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { LoginForm } from "../_hooks/use-login-form";

export function MfaForm({ login }: { login: LoginForm }) {
  const { error, loading, mfaCode } = login;

  return (
    <form onSubmit={login.handleVerifyMfa} className="space-y-4">
      {error && (
        <div id="mfa-error" className="animate-in fade-in-0 slide-in-from-bottom-2">
          <Aviso tone="danger">{error}</Aviso>
        </div>
      )}

      <Field
        label="Código de verificación"
        htmlFor="mfa-code"
        hint="Introduce el código de seis dígitos de tu app de autenticación. También puedes usar uno de tus códigos de recuperación."
      >
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
          aria-describedby={error ? "mfa-error" : undefined}
          disabled={loading}
        />
      </Field>

      <Button type="submit" className="w-full" disabled={loading || !mfaCode.trim()}>
        <ShieldCheck aria-hidden="true" />
        {loading ? "Comprobando…" : "Verificar"}
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
