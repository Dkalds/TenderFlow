"use client";

/**
 * Estado y flujos de la pantalla de acceso.
 *
 * Todo lo que puede dejar a alguien fuera del producto está aquí y no en el
 * marcado: los cinco caminos de entrada (contraseña, segundo factor, alta
 * con correo, OAuth y el atajo de desarrollo), qué error se enseña para cada fallo
 * y el canje de la invitación. `page.tsx` y sus piezas solo pintan lo que este
 * hook decide.
 *
 * El alta acaba en 201 con sesión (modo abierto: dev, E2E) o en 202 sin ella
 * (producción): la cuenta espera al enlace del correo, que lleva a
 * `/verificar-correo` (RFC 2026-10-21-alta-con-contrasena-tras-concesion).
 */

import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { useForm, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod/mini";
// De `esquemas-acceso` y no de `esquemas`: ese módulo trae los esquemas de
// todas las pantallas al First Load de `/login` (ver `esquemas-acceso.ts`).
import { acceso, registroFormulario } from "@/lib/forms/esquemas-acceso";
import type { components } from "@/generated/api";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import * as fallos from "../_lib/fallos-acceso";
import type { AccionError, Fallo } from "../_lib/fallos-acceso";
import { getErrorMessage } from "@/lib/query-feedback";
import { safeRedirectPath } from "@/lib/safe-redirect";
import { registrarEvento } from "@/lib/analytics";
// Del store y no de `hooks/use-organization`, que arrastraría todos sus hooks.
import { olvidarOrganizacionPorDefecto } from "@/lib/organization-store";

export type Mode = "login" | "register";
export type { AccionError } from "../_lib/fallos-acceso";

type RespuestaAlta = components["schemas"]["UserInfo"] | components["schemas"]["DetailMessage"];

/**
 * Campos del acceso con correo y contraseña, con los nombres de `LoginRequest` y
 * `RegisterRequest` más la confirmación del alta.
 */
export interface CredencialesValores {
  email: string;
  password: string;
  display_name: string;
  confirm_password: string;
}

// En modo acceso los dos campos del alta existen pero no se validan.
const resolverAcceso = zodResolver(
  z.extend(acceso.esquema, { display_name: z.string(), confirm_password: z.string() }),
);
const resolverRegistro = zodResolver(registroFormulario);

/**
 * Un solo formulario sirve a los dos modos, así que el esquema se elige en cada
 * validación según el modo del momento (el `context` de react-hook-form se
 * refresca en cada render; el `resolver`, no).
 */
const resolverCredenciales: Resolver<CredencialesValores, { mode: Mode }> = (valores, contexto, opciones) =>
  contexto?.mode === "register"
    ? resolverRegistro(valores, contexto, opciones)
    : resolverAcceso(valores, contexto, opciones);

export function useLoginForm() {
  const searchParams = useSearchParams();
  // Toda sesión nueva pasa por aquí: la organización por defecto que recordaba
  // este navegador puede ser de otra persona (ver `olvidarOrganizacionPorDefecto`).
  useEffect(() => {
    olvidarOrganizacionPorDefecto();
  }, []);
  // El correo de «acceso concedido» enlaza a `?modo=registro&email=…`: abre el
  // alta con la dirección puesta. Solo cuenta al montar.
  const [mode, setMode] = useState<Mode>(() => (searchParams.get("modo") === "registro" ? "register" : "login"));
  const correoDeLaUrl = searchParams.get("email")?.trim() ?? "";
  const form = useForm<CredencialesValores, { mode: Mode }>({
    resolver: resolverCredenciales,
    context: { mode },
    defaultValues: { email: correoDeLaUrl, password: "", display_name: "", confirm_password: "" },
  });
  const [showPassword, setShowPassword] = useState(false);
  const [fallo, setFallo] = useState<Fallo | null>(() => fallos.falloDelCallback(searchParams.get("error")));
  const setError = (texto: string | null) => setFallo(texto ? { texto } : null);
  // Correo al que se mandó el enlace de activación (alta cerrada, 202) y
  // cuántas veces: mientras lo haya, el panel enseña «Revisa tu correo».
  const [pendiente, setPendiente] = useState<{ correo: string; envios: number } | null>(null);
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
    form.clearErrors();
  }

  /** De la cuenta sin activar al alta con el mismo correo, que manda otro enlace. */
  function pedirOtroEnlace() {
    switchMode("register");
    setTimeout(() => form.setFocus("confirm_password"), 0);
  }

  async function login({ email, password }: CredencialesValores) {
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
      setFallo(fallos.falloDelAcceso(err));
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
      setFallo(fallos.falloDelSegundoFactor(err));
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

  // La coincidencia de contraseñas y la política de la contraseña ya las ha
  // comprobado el esquema del alta antes de llegar aquí.
  async function register({ email, password, display_name }: CredencialesValores) {
    setError(null);
    setLoading(true);
    try {
      const respuesta = await apiMutate<RespuestaAlta>("POST", "/api/v1/auth/register", {
        email,
        password,
        display_name: display_name.trim() || undefined,
      });
      // Alta cerrada (202): no hay sesión hasta que se pulse el enlace del
      // correo. Se distingue por el cuerpo porque `apiMutate` no expone el
      // estado: el 201 trae el usuario (`user_id`) y el 202 solo un `detail`.
      if (!("user_id" in respuesta)) {
        setPendiente((previo) => ({
          correo: email,
          envios: previo?.correo === email ? previo.envios + 1 : 1,
        }));
        return;
      }
      // Alta abierta (201): la API ya dejó la cookie de sesión. Solo aquí se
      // entra de verdad; en el alta cerrada el evento lo manda
      // `/verificar-correo` al activar la cuenta.
      registrarEvento("sesion_iniciada", { metodo: "registro" });
      await canjearInvitacion();
      window.location.href = "/resumen";
    } catch (err) {
      setFallo(fallos.falloDelAlta(err));
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
      setError(err instanceof Error ? getErrorMessage(err, "accion") : `No se pudo conectar con ${nombre}.`);
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
      setError(err instanceof Error ? err.message : "No se pudo entrar con el acceso de desarrollo.");
    } finally {
      setLoading(false);
    }
  }

  return {
    mode,
    isRegister: mode === "register",
    switchMode,
    form,
    showPassword,
    toggleShowPassword: () => setShowPassword((v) => !v),
    error: fallo?.texto ?? null,
    /** Lo que se ofrece junto al error, si hay algo que hacer con él. */
    errorAccion: (fallo?.accion ?? null) as AccionError | null,
    loading,
    invitacion,
    mfaPending,
    mfaCode,
    setMfaCode,
    // `handleSubmit` se llama dentro del evento, no al renderizar: así el
    // compilador de React no toma `login`/`register` por código de render.
    handleLogin: (e: FormEvent) => form.handleSubmit(login)(e),
    handleRegister: (e: FormEvent) => form.handleSubmit(register)(e),
    /** Correo al que se envió el enlace de activación, o `null` si no hay ninguno pendiente. */
    correoPendiente: pendiente?.correo ?? null,
    /** ¿Ya se ha pedido otro enlace desde «Revisa tu correo»? */
    enlaceReenviado: (pendiente?.envios ?? 0) > 1,
    /** Repite el alta con los mismos datos: la API manda otro enlace e invalida el anterior. */
    reenviarEnlace: () => form.handleSubmit(register)(),
    /** Vuelve del «Revisa tu correo» al formulario, para corregir el correo. */
    volverAlFormulario: () => {
      setPendiente(null);
      setError(null);
    },
    pedirOtroEnlace,
    handleVerifyMfa,
    cancelarMfa,
    handleOAuthLogin,
    handleDevLogin,
    /** Adónde lleva la entrada: el `?redirect=` saneado, o `/resumen`. */
    destino: destino(),
    /** Cierra la sesión abierta y vuelve a `/login` (misma revocación que el MFA). */
    cerrarSesion: cancelarMfa,
  };
}

export type LoginForm = ReturnType<typeof useLoginForm>;
