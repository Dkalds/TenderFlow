"use client";

/**
 * Atajo de desarrollo. `process.env.NODE_ENV` se sustituye en tiempo de build,
 * así que en producción el bloque entero cae con el tree-shaking y el botón no
 * existe en el bundle — no es solo que no se pinte.
 */

import { Button } from "@/components/ui/button";
import { Separador } from "./separador";

export function DevLogin({ disabled, onLogin }: { disabled: boolean; onLogin: () => Promise<void> }) {
  if (process.env.NODE_ENV !== "development") return null;

  return (
    <>
      <Separador etiqueta="dev" />
      <Button variant="secondary" className="w-full" onClick={() => void onLogin()} disabled={disabled}>
        Dev Login (user #1)
      </Button>
    </>
  );
}
