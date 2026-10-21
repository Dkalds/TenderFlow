"use client";

/**
 * Lo que queda tras el alta cerrada: la API respondió 202, no hay sesión y la
 * cuenta espera a que se abra el enlace del correo (`/verificar-correo`).
 *
 * Sustituye a las pestañas y al formulario, como `SesionAbierta`: no hay nada
 * más que rellenar. Ofrece las dos salidas que tiene quien no ve el correo:
 * pedir otro enlace (repite el alta con los mismos datos, y la API invalida el
 * anterior) o volver al formulario para corregir la dirección.
 *
 * El aviso es `role="status"`: el cambio de pantalla se anuncia sin mover el
 * foco. Un fallo al reenviar (el 429 de la cuota, por ejemplo) se pinta aquí
 * mismo, porque el formulario ya no está.
 */

import { MailCheck } from "lucide-react";
import { Aviso } from "@/components/console/aviso";
import { Button } from "@/components/ui/button";
import type { LoginForm } from "../_hooks/use-login-form";
import { AvisoError } from "./aviso-error";

export function RevisaCorreo({ login }: { login: LoginForm }) {
  const { correoPendiente, enlaceReenviado, error, loading } = login;

  return (
    <div className="space-y-4">
      <Aviso tone="success" icon={MailCheck} title="Revisa tu correo">
        {enlaceReenviado ? "Te hemos enviado otro enlace a " : "Te hemos enviado un enlace a "}
        <strong className="font-semibold break-all">{correoPendiente}</strong> para activar la cuenta. Al abrirlo
        entrarás en TenderFlow.
      </Aviso>

      {error && <AvisoError id="login-error" texto={error} accion={login.errorAccion} />}

      <p className="text-muted-foreground text-tf-meta leading-relaxed">
        Si no te llega en unos minutos, mira en la carpeta de correo no deseado o pide otro enlace. Solo vale el último
        que te enviemos.
      </p>

      <Button type="button" className="w-full" disabled={loading} onClick={() => void login.reenviarEnlace()}>
        {loading ? "Enviando…" : "Volver a enviar el enlace"}
      </Button>
      <Button type="button" variant="ghost" className="w-full" disabled={loading} onClick={login.volverAlFormulario}>
        Usar otro correo
      </Button>
    </div>
  );
}
