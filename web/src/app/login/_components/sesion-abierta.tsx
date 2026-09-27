"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";

/**
 * Lo que ve en `/login` quien ya tiene la sesión abierta (auditoría F55): la
 * cabecera pública ofrece «Iniciar sesión» siempre, y antes esta pantalla
 * respondía con el formulario vacío, como si no supiera quién era.
 *
 * No redirige sola, y es a propósito: el proxy no puede distinguir una cookie
 * válida de una caducada sin preguntar a la API, y redirigir desde ahí con una
 * cookie caducada formaría un bucle `/login` ↔ `/resumen`. Aquí la sesión ya
 * está comprobada (`/auth/me` respondió), así que basta con ofrecer las dos
 * salidas: seguir adonde iba, o cerrar esta sesión y entrar con otra cuenta.
 *
 * Sin `role="status"`: no es un cambio de estado que anunciar, es el contenido
 * de la pantalla, y el único `status` de la puerta es el aviso de invitación.
 */
export function SesionAbierta({
  email,
  destino,
  onCambiarCuenta,
}: {
  email: string;
  /** Ruta saneada del `?redirect=` (por defecto `/resumen`). */
  destino: string;
  onCambiarCuenta: () => Promise<void>;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm">
        Ya has entrado como <strong className="font-semibold break-all">{email}</strong>.
      </p>
      <Button asChild className="w-full">
        <Link href={destino}>{destino === "/resumen" ? "Ir a Resumen" : "Continuar"}</Link>
      </Button>
      <Button type="button" variant="ghost" className="w-full" onClick={() => void onCambiarCuenta()}>
        Entrar con otra cuenta
      </Button>
    </div>
  );
}
