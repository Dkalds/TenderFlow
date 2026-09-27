/**
 * Un mismo icono = un mismo concepto. Única fuente del glifo de cada entidad,
 * de cada acción recurrente y de cada espacio de la consola.
 *
 * Los iconos se elegían buscando la palabra («importe» → `DollarSign`, «total»
 * → `Hash») y el resultado era que `Building2` significaba a la vez cuenta,
 * empresa y órgano, y que el rail repetía glifo en tres pares de espacios. Con
 * el mapa aquí, la paleta de comandos, el rail y las fichas dibujan lo mismo
 * para lo mismo.
 *
 * Reglas (las mismas del comentario de escala de `globals.css`):
 * - Solo lucide. Tallas `h-3 w-3` junto a `text-tf-micro`/`text-tf-meta`,
 *   `h-3.5 w-3.5` en botones pequeños, `h-4 w-4` por defecto; más grande solo
 *   en un vacío de página.
 * - Las métricas (importe, recuento, porcentaje) **no llevan icono**. Nunca
 *   `DollarSign` ni `CircleDollarSign` para euros: sin icono, o `Euro`.
 * - La IA se nombra, no se adorna: `MessageSquareText` en `text-muted-foreground`
 *   donde haga falta un glifo. Nunca `Sparkles`.
 * - Sin icono decorativo delante de títulos de panel, tarjeta o sección.
 * - `ExternalLink` solo para salir de TenderFlow; «ir a» dentro de la app es
 *   `ArrowRight` detrás del texto (`EnlaceIr`).
 */
import {
  ArrowRight,
  Bell,
  Binoculars,
  BookUser,
  Briefcase,
  Building2,
  CalendarClock,
  CircleAlert,
  CircleCheck,
  Download,
  ExternalLink,
  Eye,
  FileText,
  Handshake,
  Info,
  Landmark,
  LayoutDashboard,
  ListChecks,
  ListFilter,
  MessageSquareText,
  Plus,
  Presentation,
  RadioTower,
  RotateCcw,
  Search,
  ServerCog,
  Settings2,
  ShieldCheck,
  Star,
  Table2,
  TextSearch,
  TriangleAlert,
  Trophy,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

/**
 * Entidades del dominio. Una cuenta es un cliente con sus órganos, pero se
 * trabaja como una ficha de relación: `BookUser`, y no el `Landmark` del
 * órgano, para que las dos no se confundan en la misma lista.
 */
export const ICONO_ENTIDAD = {
  licitacion: FileText,
  expediente: FileText,
  organo: Landmark,
  organismo: Landmark,
  cuenta: BookUser,
  empresa: Building2,
  oportunidad: Briefcase,
  ute: Handshake,
  persona: UserRound,
  equipo: Users,
} as const satisfies Record<string, LucideIcon>;

/** Conceptos y acciones que se repiten por toda la consola. */
export const ICONO_CONCEPTO = {
  /** Fecha límite, plazo de presentación, próxima acción con fecha. */
  plazo: CalendarClock,
  /** Todo lo que responde un modelo: copiloto, resumen, preguntar. */
  ia: MessageSquareText,
  /** Buscar dentro de textos (pliegos, expedientes): el Investigador. */
  investigar: TextSearch,
  buscar: Search,
  filtrar: ListFilter,
  exportar: Download,
  crear: Plus,
  reintentar: RotateCcw,
  /** «Ir a» dentro de TenderFlow, detrás del texto. */
  ir: ArrowRight,
  /** Salir de TenderFlow (fuente oficial, PLACSP, documentación externa). */
  salir: ExternalLink,
  seguir: Eye,
  favorito: Star,
  alerta: Bell,
  error: CircleAlert,
  aviso: TriangleAlert,
  exito: CircleCheck,
  info: Info,
} as const satisfies Record<string, LucideIcon>;

/**
 * Un icono distinto por espacio de la consola, indexado por `ConsoleSpace.key`
 * (`lib/console-spaces.ts`). Los espacios que son una entidad usan el icono de
 * esa entidad; ninguno se repite.
 */
export const ICONO_ESPACIO = {
  resumen: LayoutDashboard,
  radar: RadioTower,
  detalle: Table2,
  oportunidades: ICONO_ENTIDAD.oportunidad,
  mercado: Binoculars,
  cuentas: ICONO_ENTIDAD.cuenta,
  direccion: Presentation,
  competencia: Trophy,
  investigador: ICONO_CONCEPTO.investigar,
  "mi-pipeline": ListChecks,
  "mi-watchlist": ICONO_CONCEPTO.seguir,
  "mi-perfil": ICONO_ENTIDAD.persona,
  ajustes: Settings2,
  empresas: ICONO_ENTIDAD.empresa,
  equipo: ICONO_ENTIDAD.equipo,
  ops: ServerCog,
} as const satisfies Record<string, LucideIcon>;

/** Icono del administrador (roles, permisos): no es un espacio. */
export const ICONO_ADMIN: LucideIcon = ShieldCheck;

export type EntidadConIcono = keyof typeof ICONO_ENTIDAD;
export type ConceptoConIcono = keyof typeof ICONO_CONCEPTO;
export type EspacioConIcono = keyof typeof ICONO_ESPACIO;
