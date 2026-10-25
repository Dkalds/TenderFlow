"use client";

/**
 * Conmutador «Iniciar sesión / Crear cuenta».
 *
 * Se monta siempre. El alta con correo y contraseña está abierta a quien tiene
 * el acceso concedido (RFC 2026-10-21-alta-con-contrasena-tras-concesion): en
 * producción la API responde 202 y manda un enlace de activación al correo, y
 * a un correo sin concesión le responde 403 `access_not_granted`, que el
 * formulario traduce con un enlace a solicitarlo. Antes la pestaña dependía de
 * `NEXT_PUBLIC_ALLOW_SELF_REGISTRATION` y en producción no salía, porque el
 * alta solo podía acabar en error; con la concesión eso dejó de ser verdad, y
 * el correo de «acceso concedido» enlaza aquí (`?modo=registro&email=…`).
 *
 * Con la piel y el teclado de las pestañas de la consola (`clasePestana`,
 * `useTeclasPestanas`): flechas, Inicio y Fin, y solo la activa en el orden de
 * tabulación. Era un segmentado propio con sombra en la pestaña activa.
 */

import { clasePestana, useTeclasPestanas } from "@/components/console/pestanas";
import type { Mode } from "../_hooks/use-login-form";

const MODOS = ["login", "register"] as const satisfies readonly Mode[];

export function AuthModeTabs({ mode, onChange }: { mode: Mode; onChange: (next: Mode) => void }) {
  const { ref, onKeyDown } = useTeclasPestanas(MODOS, mode, onChange);

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label="Iniciar sesión o crear cuenta"
      className="border-divider mb-5 flex items-center gap-0.5 border-b pb-2"
    >
      {MODOS.map((m) => (
        <button
          key={m}
          type="button"
          role="tab"
          id={`tab-${m}`}
          aria-selected={mode === m}
          aria-controls="auth-panel"
          tabIndex={mode === m ? 0 : -1}
          onKeyDown={onKeyDown}
          onClick={() => onChange(m)}
          className={clasePestana(mode === m)}
        >
          {m === "login" ? "Iniciar sesión" : "Crear cuenta"}
        </button>
      ))}
    </div>
  );
}
