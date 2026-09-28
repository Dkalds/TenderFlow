"use client";

/**
 * Formulario de correo y contraseña: sirve al acceso y al alta con los mismos
 * campos.
 *
 * Los `id` son parte del contrato de accesibilidad y de los E2E: `#email`,
 * `#password`, `#confirm-password` y el `login-error` al que apuntan los
 * `aria-describedby`. Cambiar uno rompe a la vez al lector de pantalla y a
 * `e2e/login.spec.ts`.
 *
 * Los valores los lleva react-hook-form con el esquema de `LoginRequest` o
 * `RegisterRequest` (S7.2). `noValidate` apaga los globos nativos del
 * navegador: cada campo es un `Field`, que pinta su error debajo en
 * `<id>-error` y lo enlaza por `aria-describedby`; el control añade detrás el
 * error general del formulario.
 *
 * Sin cascada de entrada: el panel entero entra una vez (`Puerta`). Solo se
 * animan los dos campos que el alta revela, porque aparecen al cambiar de
 * pestaña, y el aviso de error.
 */

import Link from "next/link";
import { LogIn, UserPlus } from "lucide-react";
import { Aviso } from "@/components/console/aviso";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { LoginForm } from "../_hooks/use-login-form";
import { CampoContrasena } from "./campo-contrasena";

const REVELADO = "animate-in fade-in-0 slide-in-from-bottom-2";

export function CredentialsForm({ login }: { login: LoginForm }) {
  const { error, loading, isRegister, showPassword } = login;
  const { register } = login.form;
  const errores = login.form.formState.errors;
  /** Lo que cada control añade al suyo propio: el error general del formulario. */
  const general = {
    "aria-describedby": error ? "login-error" : undefined,
    "aria-invalid": error ? true : undefined,
  } as const;

  return (
    <form onSubmit={isRegister ? login.handleRegister : login.handleLogin} noValidate className="space-y-4">
      {error && (
        <div id="login-error" className={REVELADO}>
          <Aviso tone="danger">{error}</Aviso>
        </div>
      )}

      {isRegister && (
        <Field label="Nombre" htmlFor="name" className={REVELADO}>
          <Input
            id="name"
            type="text"
            placeholder="Tu nombre"
            {...register("display_name")}
            autoComplete="name"
            disabled={loading}
          />
        </Field>
      )}

      <Field
        label={
          <>
            Correo electrónico
            <Obligatorio />
          </>
        }
        htmlFor="email"
        error={errores.email?.message}
      >
        <Input
          id="email"
          type="email"
          placeholder="nombre@empresa.es"
          {...register("email")}
          required
          autoComplete="email"
          {...general}
          disabled={loading}
        />
      </Field>

      <div className="space-y-2">
        <Field
          label={
            <>
              Contraseña
              <Obligatorio />
            </>
          }
          htmlFor="password"
          hint={isRegister ? "Mínimo 10 caracteres, con mayúsculas, minúsculas y un número." : undefined}
          error={errores.password?.message}
        >
          <CampoContrasena
            id="password"
            visible={showPassword}
            onAlternar={login.toggleShowPassword}
            {...register("password")}
            required
            minLength={isRegister ? 10 : undefined}
            autoComplete={isRegister ? "new-password" : "current-password"}
            {...general}
            disabled={loading}
          />
        </Field>
        {!isRegister && (
          <Link
            href="/restablecer-contrasena"
            className="text-foreground text-tf-meta focus-visible:ring-ring inline-block rounded-sm font-medium underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:outline-none"
          >
            ¿Has olvidado tu contraseña?
          </Link>
        )}
      </div>

      {isRegister && (
        <Field
          label={
            <>
              Confirmar contraseña
              <Obligatorio />
            </>
          }
          htmlFor="confirm-password"
          error={errores.confirm_password?.message}
          className={REVELADO}
        >
          <Input
            id="confirm-password"
            type={showPassword ? "text" : "password"}
            {...register("confirm_password")}
            required
            autoComplete="new-password"
            {...general}
            disabled={loading}
          />
        </Field>
      )}

      <Button type="submit" className="w-full" disabled={loading}>
        {isRegister ? <UserPlus aria-hidden="true" /> : <LogIn aria-hidden="true" />}
        {loading ? (isRegister ? "Creando cuenta…" : "Entrando…") : isRegister ? "Crear cuenta" : "Iniciar sesión"}
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
