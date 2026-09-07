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
 */

import { cn } from "@/lib/utils";
import type { Mode } from "../_hooks/use-login-form";

/**
 * ¿Se enseña la pestaña de "Crear cuenta"?
 *
 * La bandera permite reactivarla el día que el alta se abra, sin volver a
 * tocar la pantalla.
 */
export const ALTA_ABIERTA =
  process.env.NEXT_PUBLIC_ALLOW_SELF_REGISTRATION === "1" || process.env.NODE_ENV === "development";

export function AuthModeTabs({ mode, onChange }: { mode: Mode; onChange: (next: Mode) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Iniciar sesión o crear cuenta"
      className="bg-muted grid grid-cols-2 gap-1 rounded-lg p-1 text-sm font-medium"
    >
      {(["login", "register"] as const).map((m) => (
        <button
          key={m}
          type="button"
          role="tab"
          id={`tab-${m}`}
          aria-selected={mode === m}
          aria-controls="auth-panel"
          onClick={() => onChange(m)}
          className={cn(
            "focus-visible:ring-ring rounded-md px-3 py-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none",
            mode === m ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {m === "login" ? "Iniciar sesión" : "Crear cuenta"}
        </button>
      ))}
    </div>
  );
}
