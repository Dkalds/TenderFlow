"use client";

/**
 * Estado y flujos de la pantalla de acceso.
 *
 * Todo lo que puede dejar a alguien fuera del producto está aquí y no en el
 * marcado: los cinco caminos de entrada (contraseña, segundo factor, alta
 * local, OAuth y el atajo de desarrollo), qué error se enseña para cada fallo
 * y el canje de la invitación. `page.tsx` y sus piezas solo pintan lo que este
 * hook decide.
 *
 * Refactor de estructura, no de comportamiento: mismos endpoints, mismos
 * textos de error, mismo orden de efectos y mismas navegaciones duras que
 * cuando esto vivía dentro de `page.tsx`.
 */

import { useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { apiMutate, ApiError, fetchWithAuth } from "@/lib/api-client";
import { safeRedirectPath } from "@/lib/safe-redirect";
import { registrarEvento } from "@/lib/analytics";

export type Mode = "login" | "register";

const OAUTH_FALLBACK_ERROR = "No se pudo completar el inicio de sesión. Inténtalo de nuevo.";

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  invalid_state: "La sesión de inicio caducó o ya se usó. Inténtalo de nuevo.",
  oauth_failed: OAUTH_FALLBACK_ERROR,
  email_not_allowed: "Tu cuenta no tiene acceso a TenderFlow.",
};

const ERROR_CONEXION = "Error de conexión. Inténtalo de nuevo.";

export function useLoginForm() {
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(() => {
    const oauthError = searchParams.get("error");
    return oauthError ? (OAUTH_ERROR_MESSAGES[oauthError] ?? OAUTH_FALLBACK_ERROR) : null;
  });
  const [loading, setLoading] = useState(false);
  // El callback de Google vuelve con `?mfa=required` cuando la cuenta tiene
  // segundo factor: la sesión ya está creada, solo falta elevarla.
  const [mfaPending, setMfaPending] = useState(() => searchParams.get("mfa") === "required");
  const [mfaCode, setMfaCode] = useState("");
  // Token del enlace de invitación (`/login?invitacion=...`). El backend además
  // activa por correo al registrarse o entrar por OAuth; canjearlo aquí cubre
  // el caso de quien llega con el enlace y ya tenía cuenta.
  const invitacion = searchParams.get("invitacion");

  const destino = () => safeRedirectPath(searchParams.get("redirect"));

  /** Canjea la invitación si la hay; nunca bloquea la entrada al producto. */
  async function canjearInvitacion() {
    if (!invitacion) return;
    try {
      await apiMutate("POST", "/api/v1/organizations/invitations/accept", { token: invitacion });
    } catch {
      // Un token caducado, ya usado o de otro correo no puede impedir el login:
      // la sesión ya es válida y la organización se puede pedir de nuevo.
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function handleLogin(e: FormEvent) {
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
      // Denominador de todo lo demás: sin entradas, "20 exports" no se sabe si
      // son muchos o poquísimos. Ni el email ni el destino viajan al evento.
      //
      // Lo que sigue es una navegación dura, así que el evento puede quedarse
      // sin enviar si el script de analítica todavía no había arrancado. Se
      // acepta ese subconteo: retrasar la entrada al producto para asegurar una
      // métrica sería exactamente el orden de prioridades equivocado.
      registrarEvento("sesion_iniciada", { metodo: "password" });
      await canjearInvitacion();
      window.location.href = destino();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Credenciales incorrectas" : err.message);
      } else {
        setError(ERROR_CONEXION);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyMfa(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // La cookie de sesión ya existe, así que `apiMutate` adjunta el CSRF que
      // el login dejó puesto — este endpoint lo exige.
      await apiMutate("POST", "/api/v1/auth/totp/verify", { code: mfaCode.trim() });
      // Única entrada de Google que esta pantalla llega a ver: el callback
      // vuelve aquí con `?mfa=required`. La entrada con Google **sin** segundo
      // factor aterriza directamente en el dashboard y no se cuenta todavía.
      registrarEvento("sesion_iniciada", { metodo: "totp" });
      window.location.href = destino();
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
        setError(ERROR_CONEXION);
      }
      setLoading(false);
    }
  }

  /** Sale del gate de segundo factor revocando la sesión a medias. */
  async function cancelarMfa() {
    // Salir deja una sesión a medias si no se revoca: sigue siendo válida para
    // /auth/me aunque no supere el gate.
    await apiMutate("POST", "/api/v1/auth/logout").catch(() => undefined);
    window.location.href = "/login";
  }

  async function handleRegister(e: FormEvent) {
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
      // El alta self-service está apagada en producción, así que esto sólo se
      // ve el día que se abra; entonces conviene poder distinguir la primera
      // entrada de las siguientes sin tener que instrumentar nada más.
      registrarEvento("sesion_iniciada", { metodo: "registro" });
      await canjearInvitacion();
      window.location.href = "/resumen";
    } catch (err) {
      if (err instanceof ApiError) {
        // 409: email ya registrado · 400: contrasena no cumple la politica
        setError(err.status === 409 ? "Este correo ya está registrado" : err.message);
      } else {
        setError(ERROR_CONEXION);
      }
    } finally {
      setLoading(false);
    }
  }

  /**
   * Arranca el flujo OIDC del proveedor indicado.
   *
   * Un solo manejador para los dos: `/auth/oauth/{provider}/authorize` es el
   * mismo contrato para Google y para Microsoft (D17), así que duplicarlo solo
   * garantizaría que uno de los dos se quedara atrás en el próximo cambio.
   */
  async function handleOAuthLogin(provider: "google" | "microsoft", nombre: string) {
    setError(null);
    setLoading(true);
    try {
      const { authorization_url } = await fetchWithAuth<{ authorization_url: string }>(
        `/api/v1/auth/oauth/${provider}/authorize`,
      );
      window.location.href = authorization_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : `Error al conectar con ${nombre}`);
      setLoading(false);
    }
  }

  /** Atajo de desarrollo: entra como el usuario #1 sin credenciales. */
  async function handleDevLogin() {
    setError(null);
    setLoading(true);
    try {
      // `apiMutate` adjunta `X-CSRF-Token` y normaliza el error a `ApiError`
      // con el `detail` RFC-7807.
      await apiMutate("POST", "/api/v1/auth/dev-login");
      window.location.href = "/resumen";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dev login failed");
    } finally {
      setLoading(false);
    }
  }

  return {
    mode,
    isRegister: mode === "register",
    switchMode,
    email,
    setEmail,
    displayName,
    setDisplayName,
    password,
    setPassword,
    confirmPassword,
    setConfirmPassword,
    showPassword,
    toggleShowPassword: () => setShowPassword((v) => !v),
    error,
    loading,
    invitacion,
    mfaPending,
    mfaCode,
    setMfaCode,
    handleLogin,
    handleRegister,
    handleVerifyMfa,
    cancelarMfa,
    handleOAuthLogin,
    handleDevLogin,
  };
}

export type LoginForm = ReturnType<typeof useLoginForm>;
