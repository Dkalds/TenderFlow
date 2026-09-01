"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";

const GENERIC_MESSAGE =
  "Si existe una cuenta local activa, recibirás un enlace de recuperación.";

export default function PasswordResetPage() {
  return <PasswordResetContent />;
}

function PasswordResetContent() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
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
      await fetch("/api/v1/auth/password-reset/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
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
      const response = await fetch("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail || "El enlace no es válido o ha caducado.");
      }
      setMessage("Contraseña actualizada. Ya puedes iniciar sesión.");
      window.history.replaceState(window.history.state, "", window.location.pathname);
      setPassword("");
      setConfirmation("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo actualizar la contraseña.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main-content" tabIndex={-1} className="grid min-h-screen place-items-center bg-background p-4">
      <div className="w-full max-w-md space-y-5">
        <div className="flex justify-center">
          <TenderFlowLogo showText boxSize={40} />
        </div>
        {!ready ? (
          <p role="status" className="text-center text-sm text-muted-foreground">
            Preparando recuperación…
          </p>
        ) : <Card>
          <CardHeader>
            <CardTitle>Restablecer contraseña</CardTitle>
            <CardDescription>
              {token
                ? "Elige una contraseña nueva para tu cuenta local."
                : "Te enviaremos un enlace si el correo corresponde a una cuenta local activa."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {message ? (
              <div role="status" className="space-y-4 text-sm">
                <p>{message}</p>
                <Button asChild className="w-full">
                  <Link href="/login">Volver a iniciar sesión</Link>
                </Button>
              </div>
            ) : (
              <form onSubmit={token ? confirmReset : requestReset} className="space-y-4">
                {error && (
                  <p id="reset-error" role="alert" className="text-sm text-destructive">
                    {error}
                  </p>
                )}
                {token ? (
                  <>
                    <div className="space-y-1.5">
                      <label htmlFor="new-password" className="text-sm font-medium">
                        Nueva contraseña
                      </label>
                      <Input
                        id="new-password"
                        type="password"
                        autoComplete="new-password"
                        minLength={10}
                        required
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={error ? "password-hint reset-error" : "password-hint"}
                      />
                      <p id="password-hint" className="text-xs text-muted-foreground">
                        Mínimo 10 caracteres, con mayúsculas, minúsculas y un número.
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <label htmlFor="confirm-new-password" className="text-sm font-medium">
                        Confirmar contraseña
                      </label>
                      <Input
                        id="confirm-new-password"
                        type="password"
                        autoComplete="new-password"
                        required
                        value={confirmation}
                        onChange={(event) => setConfirmation(event.target.value)}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={error ? "reset-error" : undefined}
                      />
                    </div>
                  </>
                ) : (
                  <div className="space-y-1.5">
                    <label htmlFor="reset-email" className="text-sm font-medium">
                      Correo electrónico
                    </label>
                    <Input
                      id="reset-email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      aria-invalid={error ? true : undefined}
                      aria-describedby={error ? "reset-error" : undefined}
                    />
                  </div>
                )}
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading
                    ? "Procesando…"
                    : token
                      ? "Actualizar contraseña"
                      : "Enviar enlace de recuperación"}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>}
      </div>
    </main>
  );
}
