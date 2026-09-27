"use client";

/**
 * Restablecer la contraseña: pedir el enlace (sin token) o elegir la nueva
 * (con el token en el fragmento de la URL, que no viaja al servidor).
 *
 * Es el mismo recorrido que el login —se llega desde «¿Has olvidado tu
 * contraseña?»— y ahora comparte con él la carcasa (`Puerta`), el aviso de
 * error, los campos (`Field`) y la contraseña con el botón de mostrarla. Antes
 * tenía otra composición, un título que era un `div` de 12,5 px sin ningún
 * `h1`, el error en un párrafo rojo suelto y ninguna forma de volver al login
 * hasta después de enviar.
 *
 * Solo sirve a quien entra con correo y contraseña; el texto lo dice en esas
 * palabras, sin «cuenta local».
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Puerta } from "@/app/(publico)/_components/puerta";
import { Aviso } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiMutate } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/query-feedback";
import { CampoContrasena } from "@/app/login/_components/campo-contrasena";

const GENERIC_MESSAGE = "Si ese correo entra en TenderFlow con contraseña, te llegará un enlace para cambiarla.";

export default function PasswordResetPage() {
  return <PasswordResetContent />;
}

function PasswordResetContent() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [verContrasena, setVerContrasena] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    setToken(fragment.get("token")); // eslint-disable-line react-hooks/set-state-in-effect
    setReady(true);
  }, []);

  async function requestReset(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // `apiMutate` en vez de `fetch` crudo: adjunta `X-CSRF-Token` cuando hay
      // sesión y normaliza el error a `ApiError` con el `detail` RFC-7807.
      // La respuesta sigue siendo indistinguible exista o no la cuenta: la API
      // devuelve 202 con el mismo cuerpo en ambos casos (y también al limitar).
      await apiMutate("POST", "/api/v1/auth/password-reset/request", { email });
      setMessage(GENERIC_MESSAGE);
    } catch {
      setError("No se pudo enviar la solicitud. Inténtalo de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  async function confirmReset(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirmation) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setLoading(true);
    try {
      // `apiMutate` ya extrae el `detail` RFC-7807 y lo pone en `ApiError.
      // message`, que es lo que lee el `catch` de abajo.
      await apiMutate("POST", "/api/v1/auth/password-reset/confirm", { token, password });
      setMessage("Contraseña actualizada. Ya puedes iniciar sesión.");
      window.history.replaceState(window.history.state, "", window.location.pathname);
      setPassword("");
      setConfirmation("");
    } catch (caught) {
      // El `detail` de la API cuando dice qué falló («El enlace ha caducado»);
      // un mensaje humano si es la red o un 5xx, nunca el texto crudo.
      setError(caught instanceof Error ? getErrorMessage(caught, "accion") : "No se pudo actualizar la contraseña.");
    } finally {
      setLoading(false);
    }
  }

  const errorGeneral = error ? "reset-error" : undefined;

  let panel: React.ReactNode;
  if (!ready) {
    panel = (
      <p role="status" className="text-muted-foreground text-sm">
        Preparando recuperación…
      </p>
    );
  } else if (message) {
    panel = (
      <div role="status" className="space-y-4 text-sm">
        <p>{message}</p>
        <Button asChild className="w-full">
          <Link href="/login">Volver a iniciar sesión</Link>
        </Button>
      </div>
    );
  } else {
    panel = (
      <form onSubmit={token ? confirmReset : requestReset} className="space-y-4">
        {error && (
          <div id="reset-error" className="animate-in fade-in-0 slide-in-from-bottom-2">
            <Aviso tone="danger">{error}</Aviso>
          </div>
        )}
        {token ? (
          <>
            <Field
              label="Nueva contraseña"
              htmlFor="new-password"
              hint="Mínimo 10 caracteres, con mayúsculas, minúsculas y un número."
            >
              <CampoContrasena
                id="new-password"
                visible={verContrasena}
                onAlternar={() => setVerContrasena((v) => !v)}
                autoComplete="new-password"
                minLength={10}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={errorGeneral}
              />
            </Field>
            <Field label="Confirmar contraseña" htmlFor="confirm-new-password">
              <Input
                id="confirm-new-password"
                type={verContrasena ? "text" : "password"}
                autoComplete="new-password"
                required
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={errorGeneral}
              />
            </Field>
          </>
        ) : (
          <Field
            label="Correo electrónico"
            htmlFor="reset-email"
            hint="Solo para quien entra con correo y contraseña; con Google o Microsoft no hace falta."
          >
            <Input
              id="reset-email"
              type="email"
              placeholder="nombre@empresa.es"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={errorGeneral}
            />
          </Field>
        )}
        <Button type="submit" className="w-full" disabled={loading}>
          {loading
            ? token
              ? "Guardando…"
              : "Enviando…"
            : token
              ? "Actualizar contraseña"
              : "Enviar enlace de recuperación"}
        </Button>
      </form>
    );
  }

  return (
    <Puerta
      titulo="Restablecer contraseña"
      lede={
        ready
          ? token
            ? "Elige una contraseña nueva."
            : "Te enviaremos un enlace para elegir una contraseña nueva."
          : undefined
      }
      panel={panel}
    >
      {/* La salida al login, antes de enviar nada. Después del envío la lleva
          el propio mensaje, y dos enlaces con el mismo nombre en la misma
          pantalla serían uno de más. */}
      {!message && (
        <Link
          href="/login"
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-2 rounded-sm text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Volver a iniciar sesión
        </Link>
      )}
    </Puerta>
  );
}
