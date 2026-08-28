import { RadioTower, Settings2, Star, type LucideIcon } from "lucide-react";

/**
 * Primeros pasos — qué cuenta como «configurado» y qué se puede afirmar.
 *
 * El acceso al producto es por invitación y se aprueba a mano: cada usuario que
 * entra ha costado mucho. Y hasta ahora aterrizaba en `/resumen` sin un solo
 * hilo del que tirar salvo «Buscar oportunidades en el Radar». Lo que hace útil
 * a TenderFlow —el perfil de scoring con tus pesos y keywords, las reglas que
 * vigilan el corpus por ti, el pursuit que pone un expediente en Tu día con
 * plazo y próximo paso— quedaba a descubrimiento espontáneo entre catorce
 * espacios.
 *
 * Dos restricciones gobiernan este módulo, y son las que explican por qué no es
 * un tour ni un checklist con un flag:
 *
 * 1. **El estado sale del servidor** (`web/AGENTS.md` §2). No hay campo
 *    `onboarding_completado` ni lo va a haber —exigiría migración—: cada paso se
 *    deriva de un dato que la API ya expone.
 * 2. **No se afirma lo que no se sabe** (ADR-014). Una query cargando o rota no
 *    es «te falta este paso»: es `cargando`/`desconocido`, y ninguno de los dos
 *    enciende la banda ni cuenta como hecho.
 *
 * Los tres pasos son cosas que cualquier usuario acaba haciendo, y por eso la
 * banda puede desaparecer sola. Invitar al equipo **no** es un paso a propósito:
 * quien trabaja solo no lo hará nunca y dejaría la banda encendida para siempre;
 * va como nota al pie, que no puntúa.
 */

/** Identificador estable de cada paso (usado en tests y en los mapas de estado). */
export type PasoId = "perfil" | "reglas" | "pursuit";

/**
 * Lo que se sabe de un paso.
 *
 * `"cargando"` y `"error"` **no** son `false`: mientras la query no ha
 * respondido —o ha fallado— el producto no puede decirle al usuario que le falta
 * algo. Colapsar los tres casos en un booleano es exactamente el error que
 * ADR-014 prohíbe.
 */
export type SenalPaso = boolean | "cargando" | "error";

export type EstadoPaso = "hecho" | "pendiente" | "cargando" | "desconocido";

export interface DefinicionPaso {
  id: PasoId;
  titulo: string;
  /** Qué gana el usuario. No es un eslogan: es la consecuencia de no hacerlo. */
  gana: string;
  /** Dónde se hace, exactamente. */
  href: string;
  cta: string;
  /** El mismo icono que el espacio de destino lleva en el rail. */
  icon: LucideIcon;
}

export const PASOS: readonly DefinicionPaso[] = [
  {
    id: "perfil",
    titulo: "Ajusta tu perfil de scoring",
    gana: "el Radar puntúa con pesos genéricos hasta que pongas los tuyos",
    href: "/mi-perfil",
    cta: "Definir pesos y keywords",
    icon: Settings2,
  },
  {
    id: "reglas",
    titulo: "Crea una regla de vigilancia",
    gana: "una regla vigila el corpus por ti y sus matches llegan a Tu día",
    href: "/mi-watchlist",
    cta: "Crear la primera regla",
    icon: Star,
  },
  {
    id: "pursuit",
    titulo: "Abre tu primer pursuit",
    gana: "es lo que da plazo, decisión Go/No-go y próximo paso a un expediente",
    href: "/radar",
    cta: "Elegir una en el Radar",
    icon: RadioTower,
  },
];

export interface PasoDerivado extends DefinicionPaso {
  estado: EstadoPaso;
}

/** Traduce la señal cruda de la API al estado que se pinta. */
export function estadoDe(senal: SenalPaso | undefined): EstadoPaso {
  if (senal === true) return "hecho";
  if (senal === false) return "pendiente";
  if (senal === "cargando") return "cargando";
  return "desconocido";
}

export function derivarPasos(senales: Partial<Record<PasoId, SenalPaso>>): PasoDerivado[] {
  return PASOS.map((paso) => ({ ...paso, estado: estadoDe(senales[paso.id]) }));
}

/**
 * La banda sólo se gana su sitio si hay algo **acreditadamente** pendiente.
 *
 * Con todo hecho no aparece (un veterano no ve nunca un cartel de bienvenida) y
 * mientras se comprueba tampoco: preferimos que entre tarde a que aparezca
 * afirmando una carencia que luego resulta falsa.
 */
export function debeMostrarse(pasos: readonly PasoDerivado[]): boolean {
  return pasos.some((paso) => paso.estado === "pendiente");
}

export interface Progreso {
  hechos: number;
  total: number;
  /** Cargando + fallidos: lo que no se puede contar ni a favor ni en contra. */
  sinResolver: number;
}

export function progresoDe(pasos: readonly PasoDerivado[]): Progreso {
  return {
    hechos: pasos.filter((paso) => paso.estado === "hecho").length,
    total: pasos.length,
    sinResolver: pasos.filter((paso) => paso.estado === "cargando" || paso.estado === "desconocido")
      .length,
  };
}

/**
 * Rótulo del progreso. Cuando queda algo sin comprobar lo dice: «1 de 3 hechos»
 * a secas invitaría a leer los otros dos como pendientes confirmados.
 */
export function etiquetaProgreso(progreso: Progreso): string {
  const base = `${progreso.hechos} de ${progreso.total} hechos`;
  if (progreso.sinResolver === 0) return base;
  return `${base} · ${progreso.sinResolver} sin comprobar`;
}

/**
 * Progreso tal como puede viajar en telemetría: dimensión categórica cerrada.
 *
 * El catálogo de `lib/analytics.ts` sólo admite valores enumerables leyendo el
 * fichero, y un contador libre no lo es. De ahí que sea un string de tres
 * valores y no un número.
 *
 * El tope en `"2"` no es un recorte arbitrario: la banda no se pinta con los
 * tres pasos hechos (`debeMostrarse`), así que «ocultar con todo hecho» no es
 * un estado alcanzable y `"3"` sería una categoría muerta. Clampar además deja
 * la dimensión cerrada si algún día se añade un cuarto paso — la cardinalidad
 * de una métrica no puede crecer sin que nadie lo decida.
 */
export type ProgresoOnboarding = "0" | "1" | "2";

export function progresoParaTelemetria(progreso: Progreso): ProgresoOnboarding {
  if (progreso.hechos <= 0) return "0";
  if (progreso.hechos === 1) return "1";
  return "2";
}
