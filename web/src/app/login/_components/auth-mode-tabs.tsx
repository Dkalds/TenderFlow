"use client";

/**
 * Conmutador «Iniciar sesión / Crear cuenta».
 *
 * Solo se monta cuando el alta self-service está abierta: en producción
 * `ALLOW_SELF_REGISTRATION` está apagado y no se declara en `render.yaml`, así
 * que `POST /auth/register` responde 403. La pestaña seguía ahí igualmente:
 * quien llegaba desde la landing rellenaba un formulario completo para recibir
 * un error. Es el mismo fondo de saco que motivó `lib/contacto`, un paso más
 * adelante en el embudo.
 *
 * Con la piel y el teclado de las pestañas de la consola (`clasePestana`,
 * `useTeclasPestanas`): flechas, Inicio y Fin, y solo la activa en el orden de
 * tabulación. Era un segmentado propio con sombra en la pestaña activa.
 */

import { clasePestana, useTeclasPestanas } from "@/components/console/pestanas";
import type { Mode } from "../_hooks/use-login-form";

/**
 * ¿Se enseña la pestaña de "Crear cuenta"?
 *
 * La bandera permite reactivarla el día que el alta se abra, sin volver a
 * tocar la pantalla.
 */
export const ALTA_ABIERTA =
  process.env.NEXT_PUBLIC_ALLOW_SELF_REGISTRATION === "1" || process.env.NODE_ENV === "development";

const MODOS = ["login", "register"] as const satisfies readonly Mode[];

export function AuthModeTabs({ mode, onChange }: { mode: Mode; onChange: (next: Mode) => void }) {
  const { ref, onKeyDown } = useTeclasPestanas(MODOS, mode, onChange);

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label="Iniciar sesión o crear cuenta"
      className="border-border/60 mb-5 flex items-center gap-0.5 border-b pb-2"
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
