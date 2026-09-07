"use client";

/**
 * Formulario de cuenta local: sirve al acceso y al alta con los mismos campos.
 *
 * Los `id` son parte del contrato de accesibilidad y de los E2E: `#email`,
 * `#password`, `#confirm-password` y el `login-error` al que apuntan los
 * `aria-describedby`. Cambiar uno rompe a la vez al lector de pantalla y a
 * `e2e/login.spec.ts`.
 */

import { AlertCircle, Eye, EyeOff, LogIn, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { LoginForm } from "../_hooks/use-login-form";

export function CredentialsForm({ login }: { login: LoginForm }) {
  const { error, loading, isRegister, showPassword } = login;
  const errorId = error ? "login-error" : undefined;

  return (
    /* tf-stagger cascades each direct child's entrance (reusing the app's one
       stagger token instead of hand-tuning a one-off value —
       review-animations: consolidate near-identical timing instead of
       fragmenting it). Only ever seen once per session, so the brief cascade is
       delight, not friction. */
    <form
      onSubmit={isRegister ? login.handleRegister : login.handleLogin}
      className="tf-stagger space-y-4"
    >
      {error && (
        <div
          id="login-error"
          role="alert"
          aria-live="polite"
          className="animate-in fade-in-0 slide-in-from-bottom-2 bg-destructive/10 text-destructive flex items-center gap-2 rounded-md p-3 text-sm"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {isRegister && (
        <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
          <label htmlFor="name" className="text-foreground text-sm font-medium">
            {"Nombre"}
          </label>
          <Input
            id="name"
            type="text"
            placeholder="Tu nombre"
            value={login.displayName}
            onChange={(e) => login.setDisplayName(e.target.value)}
            autoComplete="name"
            disabled={loading}
          />
        </div>
      )}

      <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
        <label htmlFor="email" className="text-foreground text-sm font-medium">
          {"Correo electrónico"}
          <Obligatorio />
        </label>
        <Input
          id="email"
          type="email"
          placeholder="tu@email.com"
          value={login.email}
          onChange={(e) => login.setEmail(e.target.value)}
          required
          autoComplete="email"
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId}
          disabled={loading}
        />
      </div>

      <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
        <label htmlFor="password" className="text-foreground text-sm font-medium">
          {"Contraseña"}
          <Obligatorio />
        </label>
        <div className="relative">
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            value={login.password}
            onChange={(e) => login.setPassword(e.target.value)}
            required
            minLength={isRegister ? 10 : undefined}
            autoComplete={isRegister ? "new-password" : "current-password"}
            aria-invalid={error ? true : undefined}
            aria-describedby={
              [isRegister ? "password-hint" : null, errorId ?? null].filter(Boolean).join(" ") ||
              undefined
            }
            disabled={loading}
          />
          <button
            type="button"
            aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
            onClick={login.toggleShowPassword}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1/2 right-0.5 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-md focus-visible:ring-2 focus-visible:outline-none"
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {isRegister && (
          <p id="password-hint" className="text-muted-foreground text-xs">
            {"Mínimo 10 caracteres, con mayúsculas, minúsculas y un número"}
          </p>
        )}
        {!isRegister && (
          <a
            href="/restablecer-contrasena"
            className="inline-block text-xs font-medium text-foreground underline-offset-4 hover:underline"
          >
            ¿Has olvidado tu contraseña?
          </a>
        )}
      </div>

      {isRegister && (
        <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
          <label htmlFor="confirm-password" className="text-foreground text-sm font-medium">
            {"Confirmar contraseña"}
            <Obligatorio />
          </label>
          <Input
            id="confirm-password"
            type={showPassword ? "text" : "password"}
            value={login.confirmPassword}
            onChange={(e) => login.setConfirmPassword(e.target.value)}
            required
            autoComplete="new-password"
            aria-invalid={error ? true : undefined}
            aria-describedby={errorId}
            disabled={loading}
          />
        </div>
      )}

      <Button type="submit" className="animate-in fade-in-0 slide-in-from-bottom-2 w-full" disabled={loading}>
        {isRegister ? <UserPlus className="mr-2 h-4 w-4" /> : <LogIn className="mr-2 h-4 w-4" />}
        {loading ? "Cargando…" : isRegister ? "Crear cuenta" : "Iniciar sesión"}
      </Button>
    </form>
  );
}

/** Asterisco de campo obligatorio, decorativo: la exigencia la dice `required`. */
function Obligatorio() {
  return (
    <span className="text-destructive ml-1" aria-hidden="true">
      *
    </span>
  );
}
