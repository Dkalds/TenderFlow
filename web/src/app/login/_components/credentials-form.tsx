"use client";

/**
 * Formulario de cuenta local: sirve al acceso y al alta con los mismos campos.
 *
 * Los `id` son parte del contrato de accesibilidad y de los E2E: `#email`,
 * `#password`, `#confirm-password` y el `login-error` al que apuntan los
 * `aria-describedby`. Cambiar uno rompe a la vez al lector de pantalla y a
 * `e2e/login.spec.ts`.
 *
 * Los valores los lleva react-hook-form con el esquema de `LoginRequest` o
 * `RegisterRequest` (S7.2). `noValidate` apaga los globos nativos del
 * navegador: el error de cada campo sale debajo de él, en `<id>-error`, y el
 * campo lo enlaza por `aria-describedby` delante del error general.
 */

import { AlertCircle, Eye, EyeOff, LogIn, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import type { LoginForm } from "../_hooks/use-login-form";

export function CredentialsForm({ login }: { login: LoginForm }) {
  const { error, loading, isRegister, showPassword } = login;
  const { register } = login.form;
  const errores = login.form.formState.errors;
  const errorId = error ? "login-error" : undefined;
  /** ARIA de un campo: su propio error primero, luego el general. */
  const aria = (campoId: string, mensaje: string | undefined, ...otros: Array<string | null>) => {
    const propios = ariaCampo(campoId, mensaje, ...otros, errorId);
    return { ...propios, "aria-invalid": error ? true : propios["aria-invalid"] };
  };

  return (
    /* tf-stagger cascades each direct child's entrance (reusing the app's one
       stagger token instead of hand-tuning a one-off value —
       review-animations: consolidate near-identical timing instead of
       fragmenting it). Only ever seen once per session, so the brief cascade is
       delight, not friction. */
    <form
      onSubmit={isRegister ? login.handleRegister : login.handleLogin}
      noValidate
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
            {...register("display_name")}
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
          {...register("email")}
          required
          autoComplete="email"
          {...aria("email", errores.email?.message)}
          disabled={loading}
        />
        <CampoError campoId="email" mensaje={errores.email?.message} />
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
            {...register("password")}
            required
            minLength={isRegister ? 10 : undefined}
            autoComplete={isRegister ? "new-password" : "current-password"}
            {...aria("password", errores.password?.message, isRegister ? "password-hint" : null)}
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
        <CampoError campoId="password" mensaje={errores.password?.message} />
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
            {...register("confirm_password")}
            required
            autoComplete="new-password"
            {...aria("confirm-password", errores.confirm_password?.message)}
            disabled={loading}
          />
          <CampoError campoId="confirm-password" mensaje={errores.confirm_password?.message} />
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
