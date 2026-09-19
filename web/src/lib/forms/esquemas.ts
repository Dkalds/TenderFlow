/**
 * Esquemas de los seis formularios con validación (S7.2): acceso, reglas de
 * seguimiento, perfil de scoring, equipo, oportunidad y webhooks.
 *
 * Todos salen de `esquemaDeDto`, así que sus claves son las del DTO generado y
 * cada clave del DTO que el formulario no rellena está declarada en
 * `omitidas` con su motivo. `CONTRATOS_DE_FORMULARIO` los reúne para el test
 * de deriva contra `src/generated/api.d.ts`.
 *
 * Los límites repiten los del backend (se cita el modelo Pydantic en cada
 * uno); los textos de error son de esta capa y no prometen nada que el backend
 * no haga.
 */

import * as z from "zod/mini";
import type { components } from "@/generated/api";
import { MOTIVOS_PERDIDA, type MotivoPerdida } from "@/lib/motivos-perdida";
import { esquemaDeDto, type ContratoDto } from "./dto-schema";
import { correo, enteroOpcional, importeOpcional, numeroDeTexto, textoOpcional } from "./valores";

type Schemas = components["schemas"];

/* ------------------------------------------------------------------ Acceso */

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

/* ------------------------------------------------------------------ Reglas */

const FRECUENCIAS = [
  "immediate",
  "daily",
  "weekly",
] as const satisfies readonly Schemas["WatchlistRuleBody"]["frequency"][];
const BANDAS = ["Caliente", "Atractiva", "Tibia", "Descarte"] as const satisfies readonly NonNullable<
  Schemas["WatchlistRuleBody"]["banda_min"]
>[];

/**
 * Criterios de una regla (`api/routes/watchlist_rules.py::WatchlistRuleBody`)
 * tal y como los edita el panel lateral. Vacío es «este criterio no filtra».
 */
export const regla = esquemaDeDto("WatchlistRuleBody")(
  {
    keyword: textoOpcional(200),
    cpv: textoOpcional(20),
    min_importe: importeOpcional,
    ccaa: z.string(),
    frequency: z.enum(FRECUENCIAS),
    tecnologia: z.string(),
    organo: textoOpcional(200),
    procedimiento: z.string(),
    tipo_contrato: z.string(),
    banda_min: z.union([z.literal(""), z.enum(BANDAS)]),
    plazo_min_dias: enteroOpcional(0, 365),
  },
  // `nombre` se deriva del primer criterio con texto; `active` lo decide el
  // switch de la tarjeta, no el formulario; organización y visibilidad son las
  // del ámbito activo.
  ["nombre", "active", "organization_id", "visibility"],
);

/**
 * Alta rápida de «Nueva regla»: cinco campos y la palabra clave obligatoria.
 * Los seis criterios de S4.4 se afinan después en el panel de edición.
 */
export const nuevaRegla = esquemaDeDto("WatchlistRuleBody")(
  {
    keyword: textoOpcional(200).check(z.refine((valor) => valor.trim() !== "", "Escribe una palabra clave.")),
    cpv: textoOpcional(20),
    min_importe: importeOpcional,
    ccaa: z.string(),
    frequency: z.enum(FRECUENCIAS),
  },
  [
    "nombre",
    "active",
    "organization_id",
    "visibility",
    "tecnologia",
    "organo",
    "procedimiento",
    "tipo_contrato",
    "banda_min",
    "plazo_min_dias",
  ],
);

/* ------------------------------------------------------------------ Perfil */

/** `api/routes/me.py::UserProfileBody`. */
export const perfil = esquemaDeDto("UserProfileBody")(
  {
    weights: z.record(z.string(), z.int().check(z.minimum(0), z.maximum(100))),
    afinidad_keywords: z.array(z.string()),
    // `_CPV_RE` y `_MAX_CPVS` del backend.
    cpvs: z
      .array(z.string().check(z.regex(/^\d{4,8}$/, "Un CPV son entre 4 y 8 dígitos.")))
      .check(z.maxLength(50, "Máximo 50 CPVs por perfil.")),
    importe_min: importeOpcional,
    importe_max: importeOpcional,
    visibility: z.enum(["private", "organization"]),
  },
  // Siempre la organización activa: no es un campo que se edite aquí.
  ["organization_id"],
);

/**
 * Un rango al revés no puntúa nada dentro: todo contrato caería «fuera de
 * rango». El backend lo guardaría igual, así que se para aquí.
 */
export const perfilFormulario = perfil.esquema.check(
  z.refine(
    (valores) => {
      const minimo = numeroDeTexto(valores.importe_min);
      const maximo = numeroDeTexto(valores.importe_max);
      return minimo == null || maximo == null || minimo <= maximo;
    },
    { path: ["importe_max"], message: "El máximo no puede ser menor que el mínimo." },
  ),
);

/* ------------------------------------------------------------------ Equipo */

/** `shared/dto.py::OrganizationCreate` (`min_length=1, max_length=200`). */
export const organizacion = esquemaDeDto("OrganizationCreate")(
  {
    name: z.string().check(z.trim(), z.minLength(1, "Escribe un nombre."), z.maxLength(200, "Máximo 200 caracteres.")),
  },
  [],
);

const ROLES_INVITABLES = [
  "admin",
  "member",
  "viewer",
] as const satisfies readonly Schemas["OrganizationMemberInvite"]["role"][];

/** `shared/dto.py::OrganizationMemberInvite`. */
export const invitacion = esquemaDeDto("OrganizationMemberInvite")(
  { email: correo, role: z.enum(ROLES_INVITABLES) },
  [],
);

/**
 * F4.1 — `shared/dto.py::OrganizationSettings.probabilidades_etapa`: un
 * entero 0-100 por etapa (`_valida_probabilidades`). Vacío es «usar el valor
 * por defecto» y no viaja: el backend aplica `PROBABILIDADES_ETAPA_DEFAULT` a
 * lo que falta, y así el formulario no congela una copia de los defaults.
 * Las etapas válidas no se enumeran aquí: las trae la respuesta
 * (`probabilidades_etapa_default`).
 */
export const probabilidadesEtapa = esquemaDeDto("OrganizationSettings")(
  {
    probabilidades_etapa: z.record(z.string(), enteroOpcional(0, 100)),
  },
  // El resto de la configuración (tecnologías, ámbito de mercado F6.1) se
  // edita en Mi Perfil; el PUT la reenvía tal cual está guardada.
  [
    "tecnologias",
    "cpvs",
    "ccaas",
    "importe_min",
    "importe_max",
    "tipos_organo",
    "procedimientos_excluidos",
  ],
);

/* -------------------------------------------------------------- Oportunidad */

type PursuitUpdate = Schemas["PursuitUpdate"];

const ESTADOS = [
  "identified",
  "qualifying",
  "go_no_go",
  "preparing",
  "submitted",
  "won",
  "lost",
  "withdrawn",
] as const satisfies readonly NonNullable<PursuitUpdate["status"]>[];
const DECISIONES = ["pending", "go", "no_go"] as const satisfies readonly NonNullable<PursuitUpdate["decision"]>[];
const CODIGOS_MOTIVO_PERDIDA = MOTIVOS_PERDIDA.map((motivo) => motivo.codigo) as [MotivoPerdida, ...MotivoPerdida[]];
const RESULTADOS = ["pending", "won", "lost", "cancelled"] as const satisfies readonly NonNullable<
  PursuitUpdate["outcome"]
>[];

/** `shared/dto.py::PursuitUpdate`, en lo que edita la ficha de la oportunidad. */
export const oportunidad = esquemaDeDto("PursuitUpdate")(
  {
    status: z.enum(ESTADOS),
    responsible_user_id: z.string().check(z.regex(/^\d*$/, "Elige una persona de la lista.")),
    decision: z.enum(DECISIONES),
    decision_reason: textoOpcional(4000),
    offer_price_eur: importeOpcional,
    outcome: z.enum(RESULTADOS),
    awarded_amount_eur: importeOpcional,
    outcome_reason: textoOpcional(4000),
    // F3.1: vacío = sin elegir. La regla «perdida exige motivo» cruza campos y
    // vive en `errorDeCierre` (lib/motivos-perdida.ts), que el editor aplica
    // al guardar.
    outcome_reason_code: z.union([z.enum(CODIGOS_MOTIVO_PERDIDA), z.literal("")]),
  },
  // `expected_version` sale de la versión cargada, no de un campo; la próxima
  // acción no se edita en este formulario.
  ["expected_version", "next_action", "next_action_due"],
);

/* ---------------------------------------------------------------- Webhooks */

const FORMATOS = ["json", "slack_blocks", "teams_adaptive_card"] as const satisfies readonly NonNullable<
  Schemas["WebhookCreate"]["formato"]
>[];

/** `api/routes/webhooks.py::WebhookCreate`. */
export const webhook = esquemaDeDto("WebhookCreate")(
  {
    name: z.string().check(z.trim(), z.minLength(1, "Escribe un nombre."), z.maxLength(100, "Máximo 100 caracteres.")),
    url: z
      .string()
      .check(
        z.trim(),
        z.minLength(1, "Escribe la URL de destino."),
        z.startsWith("https://", "La URL debe empezar por https://"),
        z.maxLength(500, "Máximo 500 caracteres."),
      ),
    event_types: z.array(z.string()),
    formato: z.enum(FORMATOS),
  },
  // La organización es la que se está mirando en la consola.
  ["organization_id"],
);

/** Todos los contratos, para el test de deriva contra el OpenAPI generado. */
export const CONTRATOS_DE_FORMULARIO: Readonly<Record<string, ContratoDto>> = {
  acceso: acceso.contrato,
  registro: registro.contrato,
  regla: regla.contrato,
  nuevaRegla: nuevaRegla.contrato,
  perfil: perfil.contrato,
  organizacion: organizacion.contrato,
  invitacion: invitacion.contrato,
  probabilidadesEtapa: probabilidadesEtapa.contrato,
  oportunidad: oportunidad.contrato,
  webhook: webhook.contrato,
};
