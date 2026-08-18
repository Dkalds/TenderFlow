"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { apiMutate, ApiError } from "@/lib/api-client";
import { LogIn, UserPlus, AlertCircle, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { ParticleField } from "@/components/layout/particle-field";
import { cn } from "@/lib/utils";
import { safeRedirectPath } from "@/lib/safe-redirect";

type Mode = "login" | "register";

const OAUTH_FALLBACK_ERROR =
  "No se pudo completar el inicio de sesión con Google. Inténtalo de nuevo.";

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  invalid_state:
    "La sesión de inicio con Google caducó o ya se usó. Inténtalo de nuevo.",
  oauth_failed: OAUTH_FALLBACK_ERROR,
  email_not_allowed: "Tu cuenta de Google no tiene acceso a TenderFlow.",
};

export default function LoginPage() {
  return (
    <Suspense>
      <LoginPageContent />
    </Suspense>
  );
}

function LoginPageContent() {
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(() => {
    const oauthError = searchParams.get("error");
    return oauthError
      ? (OAUTH_ERROR_MESSAGES[oauthError] ?? OAUTH_FALLBACK_ERROR)
      : null;
  });
  const [loading, setLoading] = useState(false);
  // El callback de Google vuelve con `?mfa=required` cuando la cuenta tiene
  // segundo factor: la sesión ya está creada, solo falta elevarla.
  const [mfaPending, setMfaPending] = useState(
    () => searchParams.get("mfa") === "required",
  );
  const [mfaCode, setMfaCode] = useState("");

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const user = await apiMutate<{ mfa_required?: boolean }>("POST", "/api/v1/auth/login", {
        email,
        password,
      });
      // La contraseña deja la sesión creada pero *pendiente*: hasta verificar el
      // segundo factor el backend responde 403 en todo lo que no sea /auth/me,
      // /auth/logout y /auth/totp/verify. Redirigir aquí llevaría al usuario a
      // un dashboard que no puede cargar nada.
      if (user?.mfa_required) {
        setMfaPending(true);
        return;
      }
      window.location.href = safeRedirectPath(searchParams.get("redirect"));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Credenciales incorrectas" : err.message);
      } else {
        setError("Error de conexión. Inténtalo de nuevo.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyMfa(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // La cookie de sesión ya existe, así que `apiMutate` adjunta el CSRF que
      // el login dejó puesto — este endpoint lo exige.
      await apiMutate("POST", "/api/v1/auth/totp/verify", { code: mfaCode.trim() });
      window.location.href = safeRedirectPath(searchParams.get("redirect"));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 429
            ? "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo."
            : err.status === 401
              ? "Código incorrecto. Revisa tu app de autenticación."
              : err.message,
        );
      } else {
        setError("Error de conexión. Inténtalo de nuevo.");
      }
      setLoading(false);
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Las contraseñas no coinciden");
      return;
    }

    setLoading(true);
    try {
      // El backend setea la cookie de sesion (auto-login) al crear la cuenta.
      await apiMutate("POST", "/api/v1/auth/register", {
        email,
        password,
        display_name: displayName.trim() || undefined,
      });
      window.location.href = "/resumen";
    } catch (err) {
      if (err instanceof ApiError) {
        // 409: email ya registrado · 400: contrasena no cumple la politica
        setError(err.status === 409 ? "Este correo ya está registrado" : err.message);
      } else {
        setError("Error de conexión. Inténtalo de nuevo.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleLogin() {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/oauth/google/authorize", {
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Error al iniciar OAuth");
      }
      const { authorization_url } = await res.json();
      window.location.href = authorization_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al conectar con Google");
      setLoading(false);
    }
  }

  const isRegister = mode === "register";

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      {/* Animated particle backdrop */}
      <ParticleField className="z-0" />
      {/* Soft radial halo to calm the area behind the card and keep contrast */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-0 [background:radial-gradient(closest-side,hsl(var(--background)/0.85),transparent_70%)]"
      />

      {/* Landmark `main` con el mismo id que en el dashboard: el skip link del
          layout raíz se renderiza en todas las rutas y aquí apuntaba a un
          ancla inexistente. */}
      <main id="main-content" tabIndex={-1} className="relative z-10 w-full max-w-md space-y-8">
        {/* Logo / Title */}
        <div className="flex flex-col items-center gap-3 text-center">
          <TenderFlowLogo showText={false} boxSize={48} />
          <div>
            <h1 className="tf-display text-foreground">TenderFlow</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Análisis y seguimiento de licitaciones en tiempo real
            </p>
          </div>
        </div>

        {/* Rare, first-load-only screen: the only place a delight-tier
            entrance is warranted (find-animation-opportunities — occasional
            frequency, "delight" purpose). */}
        <Card className="border-border/70 shadow-xl backdrop-blur-sm animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-200">
          <CardHeader className="space-y-4">
            {/* Login / Register tab switcher */}
            <div
              role="tablist"
              aria-label="Iniciar sesión o crear cuenta"
              className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1 text-sm font-medium"
            >
              {(["login", "register"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  id={`tab-${m}`}
                  aria-selected={mode === m}
                  aria-controls="auth-panel"
                  onClick={() => switchMode(m)}
                  className={cn(
                    "rounded-md px-3 py-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    mode === m
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {m === "login" ? "Iniciar sesión" : "Crear cuenta"}
                </button>
              ))}
            </div>
            <CardDescription>
              {isRegister
                ? "Crea tu cuenta con correo y contraseña"
                : "Accede con tu cuenta para ver el dashboard"}
            </CardDescription>
          </CardHeader>

          <CardContent>
            {mfaPending ? (
              <form onSubmit={handleVerifyMfa} className="space-y-4">
                {error && (
                  <div
                    role="alert"
                    aria-live="polite"
                    className="animate-in fade-in-0 slide-in-from-bottom-2 flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive"
                  >
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {error}
                  </div>
                )}

                <div className="space-y-2">
                  <label htmlFor="mfa-code" className="text-sm font-medium text-foreground">
                    Código de verificación
                  </label>
                  <Input
                    id="mfa-code"
                    type="text"
                    inputMode="numeric"
                    placeholder="123456"
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value)}
                    required
                    autoComplete="one-time-code"
                    aria-describedby="mfa-hint"
                    disabled={loading}
                  />
                  <p id="mfa-hint" className="text-xs text-muted-foreground">
                    Introduce el código de seis dígitos de tu app de autenticación. También
                    puedes usar uno de tus códigos de recuperación.
                  </p>
                </div>

                <Button type="submit" className="w-full" disabled={loading || !mfaCode.trim()}>
                  <ShieldCheck className="mr-2 h-4 w-4" />
                  {loading ? "Cargando…" : "Verificar"}
                </Button>

                <Button
                  type="button"
                  variant="ghost"
                  className="w-full"
                  disabled={loading}
                  onClick={async () => {
                    // Salir deja una sesión a medias si no se revoca: sigue
                    // siendo válida para /auth/me aunque no supere el gate.
                    await apiMutate("POST", "/api/v1/auth/logout").catch(() => undefined);
                    window.location.href = "/login";
                  }}
                >
                  Cancelar y volver
                </Button>
              </form>
            ) : (
              <>
            <div id="auth-panel" role="tabpanel" aria-labelledby={`tab-${mode}`}>
              {/* tf-stagger cascades each direct child's entrance (reusing
                  the app's one stagger token instead of hand-tuning a
                  one-off value — review-animations: consolidate near-identical
                  timing instead of fragmenting it). Only ever seen once per
                  session, so the brief cascade is delight, not friction. */}
              <form
                onSubmit={isRegister ? handleRegister : handleLogin}
                className="tf-stagger space-y-4"
              >
                {error && (
                  <div
                    role="alert"
                    aria-live="polite"
                    className="animate-in fade-in-0 slide-in-from-bottom-2 flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive"
                  >
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {error}
                  </div>
                )}

                {isRegister && (
                  <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
                    <label htmlFor="name" className="text-sm font-medium text-foreground">
                      {"Nombre"}
                    </label>
                    <Input
                      id="name"
                      type="text"
                      placeholder="Tu nombre"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      autoComplete="name"
                      disabled={loading}
                    />
                  </div>
                )}

                <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
                  <label htmlFor="email" className="text-sm font-medium text-foreground">
                    {"Correo electrónico"}
                    <span className="text-destructive ml-1" aria-hidden="true">
                      *
                    </span>
                  </label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="tu@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    disabled={loading}
                  />
                </div>

                <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
                  <label htmlFor="password" className="text-sm font-medium text-foreground">
                    {"Contraseña"}
                    <span className="text-destructive ml-1" aria-hidden="true">
                      *
                    </span>
                  </label>
                  <div className="relative">
                    <Input
                      id="password"
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      minLength={isRegister ? 10 : undefined}
                      autoComplete={isRegister ? "new-password" : "current-password"}
                      aria-describedby={isRegister ? "password-hint" : undefined}
                      disabled={loading}
                    />
                    <button
                      type="button"
                      aria-label="Mostrar/ocultar contraseña"
                      onClick={() => setShowPassword((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  {isRegister && (
                    <p id="password-hint" className="text-xs text-muted-foreground">
                      {"Mínimo 10 caracteres, con mayúsculas, minúsculas y un número"}
                    </p>
                  )}
                </div>

                {isRegister && (
                  <div className="animate-in fade-in-0 slide-in-from-bottom-2 space-y-2">
                    <label
                      htmlFor="confirm-password"
                      className="text-sm font-medium text-foreground"
                    >
                      {"Confirmar contraseña"}
                      <span className="text-destructive ml-1" aria-hidden="true">
                        *
                      </span>
                    </label>
                    <Input
                      id="confirm-password"
                      type={showPassword ? "text" : "password"}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      required
                      autoComplete="new-password"
                      disabled={loading}
                    />
                  </div>
                )}

                <Button type="submit" className="animate-in fade-in-0 slide-in-from-bottom-2 w-full" disabled={loading}>
                  {isRegister ? (
                    <UserPlus className="mr-2 h-4 w-4" />
                  ) : (
                    <LogIn className="mr-2 h-4 w-4" />
                  )}
                  {loading
                    ? "Cargando…"
                    : isRegister
                      ? "Crear cuenta"
                      : "Iniciar sesión"}
                </Button>
              </form>
            </div>

            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">o</span>
              </div>
            </div>

            <Button
              variant="outline"
              className="w-full"
              onClick={handleGoogleLogin}
              disabled={loading}
            >
              <svg aria-hidden="true" className="mr-2 h-4 w-4" viewBox="0 0 24 24">
                <path
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                  fill="#4285F4"
                />
                <path
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  fill="#34A853"
                />
                <path
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  fill="#FBBC05"
                />
                <path
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  fill="#EA4335"
                />
              </svg>
              Continuar con Google
            </Button>

            {process.env.NODE_ENV === "development" && (
              <>
                <div className="relative my-6">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-border" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-card px-2 text-muted-foreground">dev</span>
                  </div>
                </div>

                <Button
                  variant="secondary"
                  className="w-full"
                  onClick={async () => {
                    setError(null);
                    setLoading(true);
                    try {
                      const res = await fetch("/api/v1/auth/dev-login", {
                        method: "POST",
                        credentials: "include",
                      });
                      if (!res.ok) {
                        const body = await res.json().catch(() => ({}));
                        throw new Error(body.detail || "Dev login failed");
                      }
                      window.location.href = "/resumen";
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Dev login failed");
                    } finally {
                      setLoading(false);
                    }
                  }}
                  disabled={loading}
                >
                  Dev Login (user #1)
                </Button>
              </>
            )}
              </>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
