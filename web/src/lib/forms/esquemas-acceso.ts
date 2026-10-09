/**
 * Esquemas de la pantalla de acceso: entrada con correo y contraseña, y alta.
 *
 * Viven aparte de `esquemas.ts` por el First Load de `/login`. Un módulo entra
 * entero en el bundle de quien importa cualquiera de sus exports —cada esquema
 * es una llamada en el nivel superior, y eso no se puede descartar—, así que
 * `/login` cargaba y evaluaba los esquemas de las reglas, el perfil, el equipo,
 * la oportunidad y los webhooks, más `lib/motivos-perdida.ts`, y engordaba con
 * cada formulario nuevo de cualquier pantalla hasta tocar su techo
 * (`web/bundle-budget.json`). Es el mismo motivo por el que existe
 * `lib/claves-raiz.ts`.
 *
 * `esquemas.ts` importa de aquí los dos contratos para
 * `CONTRATOS_DE_FORMULARIO`: el test de deriva los sigue cubriendo. Aquí no
 * entra ningún esquema que no sea de `/login`.
 */

import * as z from "zod/mini";
import { esquemaDeDto } from "./dto-schema";
import { correo } from "./valores";

/** `api/routes/auth.py::LoginRequest`. */
export const acceso = esquemaDeDto("LoginRequest")(
  {
    email: correo,
    password: z.string().check(z.minLength(1, "Escribe tu contraseña.")),
  },
  // «Recordar este equipo» no se ofrece en esta pantalla: el backend lo toma
  // a `false`, que es el comportamiento que ya tenía.
  ["remember"],
);

/**
 * `api/routes/auth.py::RegisterRequest`. La política es la de
 * `check_password_strength(min_length=10, require_special=False)`; los
 * patrones débiles («password», «123456»…) los sigue rechazando solo el
 * backend, y su mensaje llega al aviso general del formulario.
 */
export const registro = esquemaDeDto("RegisterRequest")(
  {
    display_name: z.string(),
    email: correo,
    password: z
      .string()
      .check(
        z.minLength(10, "Mínimo 10 caracteres."),
        z.regex(/[a-z]/, "Tiene que llevar alguna minúscula."),
        z.regex(/[A-Z]/, "Tiene que llevar alguna mayúscula."),
        z.regex(/\d/, "Tiene que llevar algún número."),
      ),
  },
  [],
);

/** El alta añade la confirmación, que es del formulario y no del contrato. */
export const registroFormulario = z.extend(registro.esquema, { confirm_password: z.string() }).check(
  z.refine((valores) => valores.password === valores.confirm_password, {
    path: ["confirm_password"],
    message: "Las contraseñas no coinciden",
  }),
);
