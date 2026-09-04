import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ANCLA_SOLICITUD } from "@/lib/contacto";
import { CONTENIDO } from "../_content/landing";

/**
 * Formulario de solicitud de acceso: HTML nativo, sin una línea de JavaScript.
 *
 * El CTA principal moría en un `mailto:` —que no hace nada en un escritorio
 * con webmail, no deja rastro medible y dependía de una variable de entorno
 * indocumentada— o, sin ella, en /login, donde el alta responde 403. Esto es
 * el destino real: un `<form method="post">` que envía directamente a la API
 * pública y persiste la petición en una cola que se revisa desde el panel.
 *
 * Sin `fetch`, sin estado y sin hidratación, por dos motivos. El primero es que
 * la landing es un Server Component prerenderizado y meter un formulario
 * controlado le devolvería el runtime de React que la primera ola le quitó. El
 * segundo es que un formulario nativo funciona con el JavaScript bloqueado,
 * que es justo el escenario en el que el `mailto:` también fallaba.
 *
 * El POST va directo a `/api/v1/...` y no a una Server Action: §3.8 pide que
 * el frontend hable con el backend por HTTP tipado, y un salto intermedio por
 * Next no aportaría nada. Los rewrites de `next.config.ts` lo enrutan al
 * backend, y la respuesta es un 303 a la página de gracias, así que el
 * visitante nunca ve JSON.
 *
 * El campo `website` es la trampa anti-bots: se saca del flujo de foco con
 * `tabIndex={-1}`, se oculta a los lectores de pantalla y se posiciona fuera de
 * la vista en vez de con `display:none`, que algunos bots detectan. El servidor
 * responde el mismo 303 de éxito si viene relleno, sin guardar nada.
 *
 * `tabIndex={-1}` en el `<form>` no es decorativo: es lo que hace que el CTA
 * funcione con teclado. Un salto de fragmento mueve el scroll **y** el foco,
 * pero solo si el destino es enfocable, y un `<form>` no lo es por defecto —
 * quien pulsaba "Solicita acceso" veía bajar la página y, al tabular, volvía al
 * hero, seis pantallas por encima de lo que estaba mirando. Con `-1` el
 * elemento es enfocable programáticamente sin entrar en el orden de tabulación.
 * El `focus:outline-none` que lo acompaña es por lo mismo: este foco es
 * consecuencia del salto y no navegación del usuario, así que un anillo
 * alrededor del formulario entero se leería como un error. Los controles de
 * dentro conservan el suyo.
 *
 * `Input`/`Textarea` son los primitivos del sistema de diseño y no llevan
 * `"use client"`, así que el formulario sigue siendo servidor puro. La casilla
 * y el botón se quedan nativos a propósito: el `Checkbox` y el `Button` de
 * Radix sí son cliente, y un checkbox de Radix no es un `<input>` — no se
 * enviaría con un `<form>` nativo sin JavaScript, que es justo lo que este
 * formulario necesita poder hacer.
 */
export function FormularioSolicitud() {
  return (
    <form
      id={ANCLA_SOLICITUD}
      method="post"
      action="/api/v1/publico/solicitudes-acceso"
      tabIndex={-1}
      className="border-border/70 bg-card mt-10 w-full scroll-mt-40 rounded-xl border p-6 text-left shadow-sm focus:outline-none sm:scroll-mt-24 md:mt-0"
    >
      {/* Superficie desde la que se envía, no CTA pulsado: los tres botones
          llevan al mismo ancla de este mismo formulario, así que sin
          JavaScript el navegador manda lo mismo en los tres casos. La
          atribución por CTA vive en el evento de analytics. Ver
          `db/solicitudes_acceso.py::crear_solicitud`. */}
      <input type="hidden" name="origen" value="landing" />
      <p aria-hidden="true" className="absolute left-[-9999px] h-px w-px overflow-hidden">
        <label>
          {CONTENIDO.formTrampa}
          <input name="website" type="text" tabIndex={-1} autoComplete="off" aria-label={CONTENIDO.formTrampa} />
        </label>
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor="solicitud-email" className="block text-sm font-medium">
            {CONTENIDO.formEmail}
          </label>
          <Input
            id="solicitud-email"
            name="email"
            type="email"
            required
            autoComplete="email"
            maxLength={254}
            className="mt-1.5"
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="solicitud-empresa" className="block text-sm font-medium">
            {CONTENIDO.formEmpresa}
          </label>
          <Input
            id="solicitud-empresa"
            name="empresa"
            type="text"
            autoComplete="organization"
            maxLength={200}
            className="mt-1.5"
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="solicitud-mensaje" className="block text-sm font-medium">
            {CONTENIDO.formMensaje}
          </label>
          <Textarea id="solicitud-mensaje" name="mensaje" rows={3} maxLength={2000} className="mt-1.5" />
        </div>
      </div>

      {/* El consentimiento es obligatorio en el navegador y en el servidor: un
          checkbox sin marcar ni siquiera se envía, y el endpoint rechaza el
          envío si no llega. Sin él no hay base para guardar un dato de contacto. */}
      <label className="text-muted-foreground mt-5 flex items-start gap-2.5 text-xs leading-relaxed">
        {/* `aria-labelledby` y no `aria-label`: el nombre accesible tiene que
            ser el mismo texto que se ve (WCAG 2.5.3), y así lo es literalmente. */}
        <input
          name="consentimiento"
          type="checkbox"
          required
          value="si"
          aria-labelledby="solicitud-consentimiento-texto"
          className="border-input accent-primary mt-0.5 h-4 w-4 shrink-0 rounded"
        />
        <span id="solicitud-consentimiento-texto">
          {CONTENIDO.formConsentimiento}{" "}
          <a href="/aviso-legal" className="text-foreground underline underline-offset-4">
            {CONTENIDO.formAvisoLegal}
          </a>
          .
        </span>
      </label>

      <button
        type="submit"
        className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring focus-visible:ring-offset-background mt-6 inline-flex h-11 w-full items-center justify-center rounded-md px-6 text-sm font-semibold shadow-md transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.99]"
      >
        {CONTENIDO.formEnviar}
      </button>
    </form>
  );
}
