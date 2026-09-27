"use client";

import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Contraseña con el botón de mostrarla, para el acceso, el alta y
 * `/restablecer-contrasena`. Estaba solo en el login: restablecer, que es el
 * mismo recorrido, obligaba a escribir la contraseña nueva a ciegas dos veces.
 *
 * Va dentro de un `Field`, que le pasa `aria-describedby` y `aria-invalid`
 * como a cualquier control: este componente los reenvía al `<input>`, que es
 * quien los necesita, y no al envoltorio. `ref` también llega al `<input>`
 * (react-hook-form lo registra por ahí).
 *
 * El botón mide 36 × 36 px (objetivo táctil, WCAG 2.5.8; lo mide
 * `e2e/login.spec.ts`) y su nombre dice lo que va a hacer, no el estado.
 */
export function CampoContrasena({
  visible,
  onAlternar,
  className,
  ...props
}: Omit<React.ComponentProps<typeof Input>, "type"> & {
  visible: boolean;
  onAlternar: () => void;
}) {
  return (
    <div className="relative">
      <Input {...props} type={visible ? "text" : "password"} className={cn("pr-10", className)} />
      <button
        type="button"
        aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
        onClick={onAlternar}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1/2 right-0.5 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        {visible ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
      </button>
    </div>
  );
}
