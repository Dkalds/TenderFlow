import type { Metadata } from "next";
import Link from "next/link";
import { CircleAlert, CircleCheck } from "lucide-react";

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
 */
export const metadata: Metadata = {
  title: "Solicitud recibida",
  robots: { index: false, follow: false },
};

export default async function SolicitudRecibida({ searchParams }: { searchParams: Promise<{ estado?: string }> }) {
  const { estado } = await searchParams;
  const error = estado === "error";

  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-24 text-center">
      <span
        className={`inline-flex h-12 w-12 items-center justify-center rounded-full ${
          error ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"
        }`}
      >
        {error ? (
          <CircleAlert className="h-6 w-6" aria-hidden="true" />
        ) : (
          <CircleCheck className="h-6 w-6" aria-hidden="true" />
        )}
      </span>
      <h1 className="font-display mt-6 text-3xl font-semibold tracking-[-0.02em] text-balance">
        {error ? "No hemos podido registrar la solicitud" : "Solicitud recibida"}
      </h1>
      <p className="text-muted-foreground mx-auto mt-4 max-w-[52ch] text-base leading-relaxed">
        {error
          ? "Revisa que el email sea correcto y que hayas aceptado el tratamiento de los datos, y vuelve a intentarlo."
          : "Queda anotada. El acceso se habilita a mano, con tu email o el dominio de tu empresa, así que la respuesta llega por correo y no es inmediata."}
      </p>
      <Link
        href={error ? "/#solicitar-acceso" : "/"}
        className="border-input bg-background/60 hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring focus-visible:ring-offset-background mt-8 inline-flex h-11 items-center justify-center rounded-md border px-6 text-sm font-medium transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.97]"
      >
        {error ? "Volver al formulario" : "Volver a la portada"}
      </Link>
    </section>
  );
}
