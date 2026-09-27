"use client";

import { useEffect } from "react";
import { MARCA_HEX, TF_MARK_PATHS, TF_MARK_STROKE, TF_MARK_VIEWBOX } from "@/lib/marca";
import { reportError } from "@/lib/report-error";

/**
 * Último recinto de contención: un fallo en el layout raíz o en `Providers`
 * ocurre por encima de `(dashboard)/error.tsx`, así que hasta ahora caía en la
 * pantalla por defecto de Next — en inglés, sin marca y sin salida.
 *
 * `global-error` reemplaza el documento entero, incluidos `<html>` y `<body>`:
 * no puede apoyarse en los providers, en los componentes de UI ni en la hoja de
 * la aplicación (el fallo puede venir precisamente de ahí), así que va sin
 * dependencias y con su propia hoja mínima en un `<style>`.
 *
 * Tres excepciones a esa regla, las tres razonadas:
 *
 * - `report-error`: aquí llegan los errores más graves de la aplicación —los
 *   que dejan la pantalla en blanco— y esta página los pintaba y los olvidaba.
 *   El módulo no tiene dependencias, no toca el DOM y está escrito para no
 *   lanzar nunca. El `digest` que se le enseña al usuario es el mismo que viaja
 *   en el reporte, de modo que un "Código: 1a2b3c" en un correo de soporte se
 *   cruza con la línea del log sin tener que preguntar nada más.
 * - `lib/marca.ts`: solo constantes. Los hex estaban copiados a mano y ya no
 *   coincidían con los tokens (#F0834B frente al #F39349 de `--primary`); la
 *   marca tiene un solo sitio y esta página lo lee.
 * - La hoja en `<style>`: la CSP permite estilos en línea (`style-src
 *   'unsafe-inline'`), y es lo que deja respetar el tema del sistema. Esta
 *   página iba siempre en oscuro aunque el usuario tuviera el claro. Sin
 *   `next-themes` (es un provider) no hay forma de leer la preferencia guardada,
 *   así que manda la del sistema.
 *
 * En claro, el texto secundario es la tinta al 72 % sobre el papel: el gris de
 * la marca da 2,7:1 sobre papel y no llega a AA; así llega a ~7:1.
 */
const HOJA = `
:root {
  color-scheme: dark;
  --ge-fondo: ${MARCA_HEX.tinta};
  --ge-texto: ${MARCA_HEX.papel};
  --ge-tenue: ${MARCA_HEX.gris};
  --ge-acento: ${MARCA_HEX.naranja};
  --ge-sobre-acento: ${MARCA_HEX.tinta};
}
@media (prefers-color-scheme: light) {
  :root {
    color-scheme: light;
    --ge-fondo: ${MARCA_HEX.papel};
    --ge-texto: ${MARCA_HEX.tinta};
    --ge-tenue: ${MARCA_HEX.tinta}B8;
    --ge-acento: ${MARCA_HEX.oxido};
    --ge-sobre-acento: ${MARCA_HEX.papel};
  }
}
.ge-cuerpo {
  margin: 0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background: var(--ge-fondo);
  color: var(--ge-texto);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.ge-main { width: 100%; max-width: 32rem; }
.ge-marca { display: flex; align-items: center; gap: 0.625rem; margin: 0; font-size: 1rem; font-weight: 600; }
.ge-monograma {
  display: grid;
  place-items: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 0.4375rem;
  background: var(--ge-acento);
  color: var(--ge-sobre-acento);
}
.ge-titulo { margin: 1.5rem 0 0; font-size: 1.5rem; line-height: 1.25; font-weight: 650; letter-spacing: -0.015em; }
.ge-texto { margin: 0.75rem 0 0; font-size: 0.875rem; line-height: 1.6; color: var(--ge-tenue); }
.ge-codigo {
  margin: 1rem 0 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.75rem;
  color: var(--ge-tenue);
}
.ge-boton {
  margin-top: 1.5rem;
  padding: 0.5rem 1.25rem;
  border: none;
  border-radius: 0.375rem;
  background: var(--ge-acento);
  color: var(--ge-sobre-acento);
  font: inherit;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}
.ge-boton:focus-visible { outline: 2px solid var(--ge-acento); outline-offset: 2px; }
`;

export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  /** Vuelve a pedir y a pintar lo que falló (Next 16.3; `reset` solo repinta). */
  retry: () => void;
}) {
  useEffect(() => {
    reportError("global-error", error, undefined, "global-error");
  }, [error]);

  return (
    <html lang="es">
      <head>
        <title>Error · TenderFlow</title>
        <style>{HOJA}</style>
      </head>
      <body className="ge-cuerpo">
        <main className="ge-main">
          <p className="ge-marca">
            <span className="ge-monograma" aria-hidden="true">
              <svg
                width={16}
                height={16}
                viewBox={TF_MARK_VIEWBOX}
                fill="none"
                stroke="currentColor"
                strokeWidth={TF_MARK_STROKE}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {TF_MARK_PATHS.map((d) => (
                  <path key={d} d={d} />
                ))}
              </svg>
            </span>
            TenderFlow
          </p>
          <h1 className="ge-titulo">La aplicación no ha podido arrancar</h1>
          <p className="ge-texto">
            El error ocurrió antes de que cargara la interfaz. Vuelve a intentarlo; si se repite, recarga la página o
            avisa al equipo con el código de abajo.
          </p>
          {error.digest && <p className="ge-codigo">Código: {error.digest}</p>}
          <button type="button" onClick={retry} className="ge-boton">
            Reintentar
          </button>
        </main>
      </body>
    </html>
  );
}
