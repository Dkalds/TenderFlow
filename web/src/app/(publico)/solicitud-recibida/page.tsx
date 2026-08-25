import type { Metadata } from "next";
import Link from "next/link";
import { CircleAlert, CircleCheck } from "lucide-react";
import { ANCLA_SOLICITUD } from "@/lib/contacto";
import { EventoSolicitud } from "../_components/evento-solicitud";

/**
 * Destino del 303 con el que responde `POST /publico/solicitudes-acceso`.
 *
 * Que sea una página y no un JSON es lo que permite que el formulario funcione
 * sin JavaScript: el navegador sigue la redirección y el visitante ve una
 * confirmación normal.
 *
 * `noindex` porque no es contenido: es el acuse de recibo de una acción, y
 * Google no tiene nada que hacer aquí. Se sirve igualmente sin sesión, así que
 * su prefijo entra en el control de rutas públicas del proxy.
 *
 * El `estado` distingue **qué** falló, y no solo que algo falló. Con un único
 * `?estado=error` esta página tenía que decir "revisa el email y la casilla"
 * aunque la API supiera perfectamente cuál de los dos era: quien se equivoca en
 * un formulario que ya ha perdido lo escrito y encima no sabe en qué se
 * equivocó, no lo reescribe. Lo que no vuelve son los datos: el email es un
 * dato personal y no viaja en una query string (ver el módulo de la ruta).
 */
export const metadata: Metadata = {
  title: "Solicitud recibida",
  robots: { index: false, follow: false },
};

/**
 * Mensaje por estado. Las claves son las que emite la API
 * (`ESTADO_*` en `api/routes/publico_solicitudes.py`); cualquier otra cosa —una
 * URL escrita a mano, un estado nuevo sin desplegar aquí— cae en el genérico,
 * que sigue siendo un mensaje útil y no una página rota.
 */
const FALLOS: Record<string, { titulo: string; texto: string }> = {
  email: {
    titulo: "Ese email no parece válido",
    texto:
      "Vuelve al formulario y revisa la dirección. El resto de lo que escribiste no se ha guardado: por seguridad no viaja en la URL, así que hay que ponerlo otra vez.",
  },
  consentimiento: {
    titulo: "Falta aceptar el tratamiento de los datos",
    texto:
      "Sin esa casilla marcada no hay base legal para guardar tu dirección, así que la solicitud no se registra. Está justo encima del botón de enviar.",
  },
  limite: {
    titulo: "Demasiados envíos desde tu conexión",
    texto:
      "El formulario admite unos pocos envíos por minuto y por conexión —en una oficina lo compartís todos—. Espera un minuto y vuelve a intentarlo; no se ha perdido nada.",
  },
  error: {
    titulo: "No hemos podido registrar la solicitud",
    texto:
      "Ha fallado por nuestro lado o el envío llegó incompleto. Vuelve al formulario e inténtalo otra vez.",
  },
};

export default async function SolicitudRecibida({ searchParams }: { searchParams: Promise<{ estado?: string }> }) {
  const { estado } = await searchParams;
  const fallo = estado ? (FALLOS[estado] ?? FALLOS.error) : null;

  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-24 text-center">
      {/* Único punto del embudo que sabe si el POST prosperó. */}
      <EventoSolicitud estado={fallo ? (estado ?? "error") : "ok"} />

      <span
        className={`inline-flex h-12 w-12 items-center justify-center rounded-full ${
          fallo ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"
        }`}
      >
        {fallo ? (
          <CircleAlert className="h-6 w-6" aria-hidden="true" />
        ) : (
          <CircleCheck className="h-6 w-6" aria-hidden="true" />
        )}
      </span>
      <h1 className="font-display mt-6 text-3xl font-semibold tracking-[-0.02em] text-balance">
        {fallo ? fallo.titulo : "Solicitud recibida"}
      </h1>
      <p className="text-muted-foreground mx-auto mt-4 max-w-[52ch] text-base leading-relaxed">
        {fallo
          ? fallo.texto
          : "Queda anotada. El acceso se habilita a mano, con tu email o el dominio de tu empresa, así que la respuesta llega por correo y no es inmediata."}
      </p>
      <Link
        href={fallo ? `/#${ANCLA_SOLICITUD}` : "/"}
        className="border-input bg-background/60 hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring focus-visible:ring-offset-background mt-8 inline-flex h-11 items-center justify-center rounded-md border px-6 text-sm font-medium transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.97]"
      >
        {fallo ? "Volver al formulario" : "Volver a la portada"}
      </Link>
    </section>
  );
}
