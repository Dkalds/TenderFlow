"use client";

/**
 * Activa la cuenta con el enlace del correo y entra.
 *
 * Al montar lee el token del fragmento (`#token=…`, que no viaja al servidor
 * ni a los logs de acceso), lo quita de la URL y lo canjea en
 * `POST /auth/verify-email`. Con 200 la API ya dejó la cookie de sesión, y se
 * entra con navegación dura en `/resumen`, como al final del login: el
 * `SessionProvider` tiene que arrancar con la sesión nueva.
 *
 * El token es de **un solo uso**: una segunda llamada con el mismo respondería
 * 400 y pisaría el éxito de la primera con «el enlace ha caducado». El doble
 * montaje de `StrictMode` en desarrollo hace exactamente eso, así que una ref
 * recuerda qué token se canjeó ya y no se repite. Solo un «Reintentar»
 * explícito vuelve a mandarlo, y solo tras un fallo que no lo gasta (la cuota
 * de intentos o la red).
 *
 * Misma carcasa (`Puerta`), aviso de error y forma de quitar el fragmento que
 * `/restablecer-contrasena`, que es el otro destino de un enlace del correo.
 */

import { useEffect, useEffectEvent, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Puerta } from "@/app/(publico)/_components/puerta";
import { Aviso } from "@/components/console/aviso";
import { Button } from "@/components/ui/button";
import { apiMutate, ApiError } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";
import { solicitarAccesoHref } from "@/lib/contacto";
// Del store y no de `hooks/use-organization`, que arrastraría todos sus hooks.
import { olvidarOrganizacionPorDefecto } from "@/lib/organization-store";
import { getErrorMessage } from "@/lib/query-feedback";

/** `detail` del 403 de `/auth/verify-email`: se revocó el acceso tras el alta. */
const SIN_ACCESO = "access_not_granted";

/** Adónde se entra al activar la cuenta. */
const DESTINO = "/resumen";

/** Donde se pide otro enlace: el alta con el mismo correo lo manda. */
const OTRO_ENLACE = "/login?modo=registro";

type Estado =
  | { fase: "activando" }
  | { fase: "activada" }
  | { fase: "sin_token" }
  | { fase: "caducado" }
  | { fase: "sin_acceso" }
  /** `token`: el que se reintenta; un fallo no lo gasta. */
  | { fase: "fallo"; texto: string; token?: string };

/** Navegación dura: el `SessionProvider` tiene que arrancar con la cookie nueva. */
function navegarDuro(ruta: string) {
  window.location.href = ruta;
}

/**
 * Quita el fragmento de la URL de forma que el router de Next se entere y no
 * lo reponga: `null` como estado y después de los efectos de montaje (el
 * porqué, en `restablecer-contrasena/page.tsx`).
 */
function quitarFragmento() {
  queueMicrotask(() => {
    const { pathname, search } = window.location;
    window.history.replaceState(null, "", pathname + search);
  });
}

function tokenDelFragmento(): string | null {
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
}

/** Lo que dice la API del canje, traducido a la pantalla que toca. */
async function canjear(token: string): Promise<Estado> {
  try {
    await apiMutate("POST", "/api/v1/auth/verify-email", { token });
    return { fase: "activada" };
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) return { fase: "caducado" };
    if (err instanceof ApiError && err.status === 403 && err.message === SIN_ACCESO) return { fase: "sin_acceso" };
    // 429 (cuota de intentos), red o 5xx: el enlace sigue valiendo.
    return { fase: "fallo", texto: getErrorMessage(err, "accion") };
  }
}

export function VerificacionCorreo({ irA = navegarDuro }: { irA?: (ruta: string) => void }) {
  const [estado, setEstado] = useState<Estado>({ fase: "activando" });
  // El token que ya se mandó a la API. Guarda contra el doble montaje y contra
  // un `hashchange` con el mismo enlace.
  const canjeado = useRef<string | null>(null);

  async function activar(token: string) {
    setEstado({ fase: "activando" });
    const resultado = await canjear(token);
    setEstado(resultado.fase === "fallo" ? { ...resultado, token } : resultado);
    if (resultado.fase === "activada") {
      // Sesión nueva: la organización por defecto que recordaba este navegador
      // puede ser de otra persona (ver `olvidarOrganizacionPorDefecto`).
      olvidarOrganizacionPorDefecto();
      // Primera entrada de una cuenta del alta cerrada. Va antes de la
      // navegación dura y puede perderse si la analítica no había arrancado;
      // se acepta, como en el login.
      registrarEvento("sesion_iniciada", { metodo: "registro" });
      irA(DESTINO);
    }
  }

  // Evento y no dependencia: el efecto se monta una vez y lee siempre el
  // `activar` (y el `irA`) del último render.
  const leerFragmento = useEffectEvent(() => {
    const recibido = tokenDelFragmento();
    if (recibido) {
      quitarFragmento();
      if (canjeado.current !== recibido) {
        canjeado.current = recibido;
        void activar(recibido);
      }
    } else if (canjeado.current === null) {
      setEstado({ fase: "sin_token" });
    }
  });

  useEffect(() => {
    leerFragmento();
    // Pegar el enlace en esta misma pestaña solo cambia el fragmento.
    const alCambiar = () => leerFragmento();
    window.addEventListener("hashchange", alCambiar);
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);

  let panel: React.ReactNode;
  if (estado.fase === "activando") {
    panel = (
      <p role="status" className="text-muted-foreground text-sm">
        Activando tu cuenta…
      </p>
    );
  } else if (estado.fase === "activada") {
    panel = (
      <p role="status" className="text-sm">
        Cuenta activada. Entrando en TenderFlow…
      </p>
    );
  } else if (estado.fase === "caducado") {
    panel = (
      <div className="space-y-4">
        <Aviso tone="danger" title="El enlace no es válido o ha caducado">
          Cada enlace sirve una sola vez y caduca. Si tu cuenta ya está activa, inicia sesión; si no, vuelve a darte de
          alta con el mismo correo y te enviaremos otro.
        </Aviso>
        <Button asChild className="w-full">
          <Link href={OTRO_ENLACE}>Pedir otro enlace</Link>
        </Button>
        <Button asChild variant="ghost" className="w-full">
          <Link href="/login">Iniciar sesión</Link>
        </Button>
      </div>
    );
  } else if (estado.fase === "sin_acceso") {
    panel = (
      <div className="space-y-4">
        <Aviso tone="danger" title="Este correo ya no tiene acceso a TenderFlow">
          El acceso se retiró después de crear la cuenta, así que no se ha activado.
        </Aviso>
        <Button asChild className="w-full">
          <a href={solicitarAccesoHref()}>Solicita acceso</a>
        </Button>
      </div>
    );
  } else if (estado.fase === "sin_token") {
    panel = (
      <div className="space-y-4">
        <Aviso tone="warning" title="Falta el código del enlace">
          Abre otra vez el enlace desde el correo, sin recortarlo. Si no lo encuentras, vuelve a darte de alta con el
          mismo correo y te enviaremos otro.
        </Aviso>
        <Button asChild className="w-full">
          <Link href={OTRO_ENLACE}>Pedir otro enlace</Link>
        </Button>
      </div>
    );
  } else {
    const { token } = estado;
    panel = (
      <div className="space-y-4">
        <Aviso tone="danger" title="No se pudo activar la cuenta">
          {estado.texto}
        </Aviso>
        {token && (
          <Button type="button" className="w-full" onClick={() => void activar(token)}>
            Reintentar
          </Button>
        )}
      </div>
    );
  }

  // La salida al login, salvo donde el panel ya la lleva o ya se está entrando.
  const conSalida = estado.fase === "sin_token" || estado.fase === "sin_acceso" || estado.fase === "fallo";

  return (
    <Puerta titulo="Activa tu cuenta" lede="Con el enlace que te enviamos al correo." panel={panel}>
      {conSalida && (
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
