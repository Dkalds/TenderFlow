"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, CircleAlert, RotateCcw, type LucideIcon } from "lucide-react";
import { cn, EMPTY, formatPercent } from "@/lib/utils";
import { detalleTecnico, getErrorMessage } from "@/lib/query-feedback";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { clasePestana, claseContador, useTeclasPestanas } from "./pestanas";

export { ChipBanda, esBandaConocida, type BandaPuntuacion, type ChipBandaProps } from "./chip-banda";
export { Aviso, type TonoAviso } from "./aviso";
export { clasePestana, claseContador, useTeclasPestanas } from "./pestanas";

/**
 * Vocabulario de panel de la consola.
 *
 * Es la parte del sistema de gráficos que aterriza en código: una sola forma de
 * panel, un solo título, y **los tres estados ocupando el mismo alto que el
 * gráfico real**, para que la página no salte al cargar. Antes cada pantalla
 * inventaba su tarjeta, su cabecera y su vacío, y la diferencia se notaba al
 * pasar de una a otra.
 *
 * Reglas duras que hereda del sistema de gráficos y conviene no romper:
 * - El color de serie se toma por índice de `lib/chart-colors.ts`, nunca a mano.
 * - «Otros» siempre en `chart-8`.
 * - Nunca dos ejes Y en un panel: dos paneles apilados compartiendo eje X.
 * - Clic en una marca = filtrar el ámbito, no navegar.
 *
 * Reglas de dibujo (las que estos primitivos fijan para toda la consola):
 * - **Rótulos de dato** en sans, en frase y a 11 px (`ROTULO_DATO`). Sin mono,
 *   sin versal, sin tracking. La versal queda solo en las cabeceras de columna
 *   de tabla (`CABECERA_COLUMNA` de `@/components/ui/table`).
 * - **Mono** solo para identificadores y código (expediente, CPV, NIF, claves,
 *   rutas): `Fact variant="codigo"`. Cifras, importes, fechas y palabras en
 *   sans; el `tnum` ya viene del body.
 * - **Cifra de KPI** a 20 px (`text-tf-title font-semibold`) en `StatCell`,
 *   que es el KPI canónico. `KpiCard` es un adaptador deprecado.
 * - **Superficies** opacas (`bg-card`), sin degradados ni sombra. El énfasis de
 *   un panel es su borde (`tono`), nunca un relleno de color.
 * - **Tintes**: `/5` hover, `/10` seleccionado o chip, `/15` énfasis fuerte;
 *   bordes tintados `/30` o `/40`.
 * - **Iconos**: los títulos de panel, tarjeta, sección y hoja no llevan icono
 *   (salvo el chevron de un desplegable, a la derecha). Un botón con texto no
 *   lleva icono salvo `Download` = exportar, `Plus` = crear, `RotateCcw` =
 *   reintentar, y `ExternalLink` detrás del texto cuando sale de TenderFlow. Un
 *   botón solo-icono lleva `aria-label` y `Tooltip`. El mapa entidad → icono
 *   está en `lib/iconos.ts`.
 * - **Vacíos** con `PanelEmpty`, **errores** con `PanelError`, **avisos** con
 *   `Aviso`, **«ir a»** con `EnlaceIr`, **conmutadores** con `PanelTabs`
 *   (pestañas con panel) o `Segmented` (filtros y modos con `aria-pressed`).
 */

/* ── Rótulos ──────────────────────────────────────────────────────────── */

/**
 * Rótulo de un dato (etiqueta de KPI, de `Fact`, de un par clave-valor): sans,
 * en frase, a 11 px. Una sola receta para toda la consola; antes había ~29
 * combinaciones de mono, versal y tracking para el mismo papel.
 */
export const ROTULO_DATO = "text-tf-micro font-medium text-muted-foreground";

/* ── Tonos ────────────────────────────────────────────────────────────── */

/** Tono semántico del texto de un dato. */
export type TonoDato = "success" | "destructive" | "warning" | "primary" | "muted";

const TEXTO_TONO: Record<TonoDato, string> = {
  success: "text-success",
  destructive: "text-destructive",
  warning: "text-warning",
  primary: "text-primary",
  muted: "text-muted-foreground",
};

/* ── Panel ────────────────────────────────────────────────────────────── */

/**
 * Énfasis de un panel: solo el color del borde, sobre la misma superficie
 * opaca. Exportado para las superficies que no son un `Panel` (un `<section>`
 * con su propio `aria-labelledby`): `cn(SUPERFICIE_PANEL, TONO_PANEL.accent)`.
 */
export const TONO_PANEL = {
  accent: "border-primary/40",
  danger: "border-destructive/40",
} as const;

export type TonoPanel = keyof typeof TONO_PANEL;

/** La superficie de un panel, para elementos que no pueden ser un `Panel`. */
export const SUPERFICIE_PANEL = "rounded-xl border border-border/60 bg-card";

export function Panel({
  className,
  tono,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  /** Énfasis del panel: borde primario (`accent`) o destructivo (`danger`). */
  tono?: TonoPanel;
}) {
  return (
    <div className={cn(SUPERFICIE_PANEL, "px-4 py-3.5", tono && TONO_PANEL[tono], className)} {...props}>
      {children}
    </div>
  );
}

/** Título de panel: qué es, y en una línea de qué ámbito habla. */
export function PanelTitle({
  title,
  hint,
  actions,
  as: Nivel = "h3",
  id,
  className,
}: {
  title: React.ReactNode;
  hint?: React.ReactNode;
  actions?: React.ReactNode;
  /** Nivel del encabezado; `h2` cuando el panel es una sección de la página. */
  as?: "h2" | "h3";
  /** Para el `aria-labelledby` de la sección que lo contiene. */
  id?: string;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-baseline gap-2.5", className)}>
      <Nivel id={id} className="flex-none text-tf-body font-semibold">
        {title}
      </Nivel>
      {hint && <span className="min-w-0 truncate text-tf-meta text-muted-foreground">{hint}</span>}
      {actions && <div className="ml-auto flex flex-none items-center gap-1.5">{actions}</div>}
    </div>
  );
}

/**
 * Rótulo de sección dentro de un panel o de un inspector: en frase, a 12 px,
 * semibold y en gris. `hint` va a la derecha (un recuento, una fecha).
 */
export function SectionTitle({
  as: Nivel = "h4",
  children,
  hint,
  aside,
  id,
  className,
}: {
  as?: "h3" | "h4";
  children: React.ReactNode;
  hint?: React.ReactNode;
  /** @deprecated Usa `hint`. */
  aside?: React.ReactNode;
  id?: string;
  className?: string;
}) {
  const pista = hint ?? aside;
  return (
    <div className={cn("mb-2.5 flex items-baseline justify-between gap-2", className)}>
      <Nivel id={id} className="text-tf-meta font-semibold text-muted-foreground">
        {children}
      </Nivel>
      {pista != null && pista !== false && <span className="text-tf-meta text-muted-foreground">{pista}</span>}
    </div>
  );
}

/* ── Dato suelto ──────────────────────────────────────────────────────── */

/** Cómo se lee el valor de un `Fact`. */
export type VarianteFact = "texto" | "cifra" | "codigo";

const VALOR_FACT: Record<VarianteFact, string> = {
  texto: "text-tf-body font-medium",
  cifra: "tf-tnum text-tf-body font-medium",
  codigo: "font-mono text-tf-body",
};

/**
 * Un dato suelto con su rótulo: la celda de las rejillas de ficha e inspector
 * (van en una rejilla de 1 px: `grid gap-px bg-border/60`, como `StatStrip`).
 *
 * `variant`: `texto` (por defecto), `cifra` (importe, días, score: sans con
 * cifras tabulares) o `codigo` (expediente, CPV, NIF: mono). La mono es para
 * identificadores, nunca para cifras ni palabras.
 */
export function Fact({
  label,
  value,
  variant = "texto",
  tono,
  color,
  className,
}: {
  label: React.ReactNode;
  /** Sin valor (`null`/`undefined`) pinta la raya de vacío de la casa. */
  value: React.ReactNode;
  /** `"text"` y `"mono"` son los nombres antiguos (`texto` y `codigo`). */
  variant?: VarianteFact | "text" | "mono";
  tono?: TonoDato;
  /** @deprecated Usa `tono`. Color CSS libre, solo para el score por banda. */
  color?: string;
  className?: string;
}) {
  const v: VarianteFact = variant === "text" ? "texto" : variant === "mono" ? "codigo" : variant;
  return (
    <div className={cn("min-w-0 bg-card px-3 py-2.5", className)}>
      <div className={cn("mb-1", ROTULO_DATO)}>{label}</div>
      <div
        className={cn(VALOR_FACT[v], "leading-snug", tono && TEXTO_TONO[tono])}
        style={color ? { color } : undefined}
      >
        {value ?? <span className="text-muted-foreground">{EMPTY}</span>}
      </div>
    </div>
  );
}

/* ── KPI ──────────────────────────────────────────────────────────────── */

/**
 * Tinte de una superficie pulsable que se apoya en otra (la celda de una tira
 * sobre la rejilla de 1 px): /5 al pasar y /10 al pulsar, mezclados con la
 * tarjeta y no transparentes, porque un `bg-primary/5` dejaba ver el gris de
 * la rejilla y el hover salía sucio. El pulsado va sin transición (responde en
 * el mismo frame del pointer-down) y vuelve con la del elemento.
 */
export const PULSABLE_SOBRE_TARJETA =
  "hover:bg-[color-mix(in_oklab,hsl(var(--primary))_5%,hsl(var(--card)))] active:bg-[color-mix(in_oklab,hsl(var(--primary))_10%,hsl(var(--card)))]";

/**
 * Celda de una tira de estadísticas: **el KPI canónico de la consola**. Los KPIs
 * van pegados en una rejilla de 1 px (`StatStrip`), no en cuatro tarjetas
 * separadas: leen como una sola fila de dato en vez de como cuatro objetos que
 * compiten.
 *
 * La cifra va a 20 px (`text-tf-title`), sans y seminegrita, con cifras
 * tabulares; el rótulo, a 11 px en frase (`ROTULO_DATO`).
 */
export function StatCell({
  label,
  value,
  hint,
  grafico,
  trend,
  trendAlert,
  badge,
  loading,
  onClick,
  href,
  tono,
  accent,
  className,
  "aria-label": ariaLabel,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  /**
   * El dibujo de la cifra, entre el valor y su pie: una barra de proporción,
   * una regla con zonas, doce columnas. Un gráfico mínimo que sitúa el número,
   * no un segundo dato; mientras carga no se pinta.
   */
  grafico?: React.ReactNode;
  trend?: number;
  /**
   * Sube el delta al cuerpo del valor y lo pinta en ámbar. Es para la celda que
   * ya viene marcada como anómala: con el delta pequeño, la desviación que la
   * etiqueta anunciaba había que ir a buscarla — el ojo aterrizaba en el valor
   * absoluto, que es justo el número que **no** ha cambiado.
   */
  trendAlert?: boolean;
  badge?: React.ReactNode;
  loading?: boolean;
  onClick?: () => void;
  /**
   * Destino de la celda, cuando lo tiene. Ancla de verdad y no un `onClick` con
   * `router.push`: la celda que lo estrena venía de ser una tarjeta enlazada, y
   * degradarla a botón le habría quitado el clic-central, el «abrir en pestaña
   * nueva» y el destino en la barra de estado — tres cosas que ya tenía.
   */
  href?: string;
  /** Color semántico de la cifra (un estado, no decoración). */
  tono?: "success" | "destructive" | "warning";
  /** @deprecated Usa `tono`. Color CSS libre de la cifra. */
  accent?: string;
  className?: string;
  /** Nombre accesible del enlace o botón, cuando el contenido no basta. */
  "aria-label"?: string;
}) {
  const up = (trend ?? 0) >= 0;
  const body = (
    <>
      <div className="mb-1 flex min-w-0 items-center gap-1.5">
        <span className={cn("truncate", ROTULO_DATO)}>{label}</span>
        {badge}
      </div>
      {loading ? (
        <Skeleton className="h-6 w-24 rounded-sm" />
      ) : (
        <div className="flex min-w-0 items-baseline gap-2">
          <span
            className={cn("tf-tnum truncate text-tf-title font-semibold", tono && TEXTO_TONO[tono])}
            style={accent ? { color: accent } : undefined}
          >
            {value}
          </span>
          {trend != null && (
            <span
              className={cn(
                "tf-tnum flex-none",
                trendAlert
                  ? "text-tf-title font-semibold text-warning"
                  : cn("text-tf-meta font-medium", up ? "text-success" : "text-destructive"),
              )}
            >
              {/* `formatPercent` y no `toFixed`: éste emite siempre el punto
                  decimal, y la tira sacaba «+768.9%» pegado a un «93,1%» del
                  panel de al lado. */}
              {up ? "+" : ""}
              {formatPercent(trend)}
            </span>
          )}
        </div>
      )}
      {grafico != null && !loading && <div className="mt-2">{grafico}</div>}
      {hint && <div className="mt-1 truncate text-tf-meta text-muted-foreground">{hint}</div>}
    </>
  );

  const base = cn("min-w-0 bg-card px-3.5 py-2.5", className);
  const pulsable = cn("text-left transition-colors active:duration-0", PULSABLE_SOBRE_TARJETA);

  if (href) {
    return (
      <Link href={href} data-slot="stat-cell" aria-label={ariaLabel} className={cn(pulsable, base)}>
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button
        type="button"
        data-slot="stat-cell"
        aria-label={ariaLabel}
        onClick={onClick}
        className={cn(pulsable, base)}
      >
        {body}
      </button>
    );
  }
  return (
    <div data-slot="stat-cell" className={base}>
      {body}
    </div>
  );
}

/**
 * Contenedor de una tira de `StatCell`, con la rejilla de 1 px del sistema: dos
 * columnas por debajo de `lg` y las que pida `columns` a partir de ahí.
 */
export function StatStrip({
  columns = 4,
  className,
  children,
}: {
  columns?: number;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        // Apretar seis KPIs en una pantalla de portátil los vuelve ilegibles
        // antes que compactos: dos columnas hasta `lg`.
        "grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60",
        "lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]",
        // Una celda que trae su propio marco (`KpiCard` suelto) lo pierde dentro
        // de la tira: aquí el marco es la rejilla.
        "[&_[data-slot=stat-cell]]:rounded-none [&_[data-slot=stat-cell]]:border-0",
        className,
      )}
      style={{ ["--console-stat-columns" as string]: String(columns) }}
    >
      {children}
    </div>
  );
}

/* ── Estados: carga, vacío, error ─────────────────────────────────────── */

/**
 * Los tres estados de un panel de datos, con el alto del contenido real para
 * que la página no salte cuando llega el dato.
 */
export function PanelLoading({ height = 260, className }: { height?: number; className?: string }) {
  return <Skeleton className={cn("w-full rounded-md", className)} style={{ height }} />;
}

/**
 * «No hay nada»: qué falta y, si ayuda, qué hacer. Sin baldosa de icono
 * tintada ni caja de borde discontinuo; si hace falta un icono, pequeño, gris y
 * en línea con el título.
 *
 * El texto tiene que ser concreto («Ningún CPV con adjudicaciones en el ámbito
 * actual. Amplía las fechas.»), no «Sin datos».
 */
export function PanelEmpty({
  title,
  hint,
  message,
  icon: Icono,
  action,
  size = "md",
  height,
  className,
}: {
  /** Qué falta, en una línea. */
  title?: React.ReactNode;
  /** Por qué, o qué hacer. */
  hint?: React.ReactNode;
  /** @deprecated Usa `hint` (y `title` para la primera línea). */
  message?: React.ReactNode;
  icon?: LucideIcon;
  /** Un `Button` (outline `sm`; primario solo si es el primer paso). */
  action?: React.ReactNode;
  /** `md` (por defecto) para un panel o una página; `sm` dentro de una lista. */
  size?: "sm" | "md";
  height?: number;
  className?: string;
}) {
  const pista = hint ?? message;
  const icono = Icono ? <Icono className="h-4 w-4 flex-none text-muted-foreground" aria-hidden="true" /> : null;
  return (
    <div
      // `status` y no un div mudo: pasar de «cargando» a «no hay nada» es un
      // cambio de estado que el lector de pantalla tiene que oír.
      role="status"
      className={cn("grid place-items-center px-4 text-center", size === "sm" ? "py-5" : "py-9", className)}
      style={height ? { minHeight: height } : undefined}
    >
      <div className="max-w-[420px]">
        {title && (
          <p className="inline-flex items-center gap-1.5 text-tf-body font-medium text-foreground">
            {icono}
            {title}
          </p>
        )}
        {pista && (
          <p
            className={cn(
              "text-tf-meta text-muted-foreground",
              title && "mt-1",
              !title && icono && "inline-flex items-center gap-1.5",
            )}
          >
            {!title && icono}
            {pista}
          </p>
        )}
        {action && <div className="mt-3 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}

/**
 * Un fallo en línea: mensaje humano, «Reintentar» y el «Detalle técnico»
 * plegado. **Un solo aviso por fallo**: la consulta cuyo error se pinta aquí
 * lleva `meta: META_ERROR_EN_LINEA` (`lib/query-feedback`) para no lanzar
 * además el toast.
 *
 * - `error`: lo que lanzó la consulta. Da el mensaje visible
 *   (`getErrorMessage`) y el detalle técnico (estado, método y ruta).
 * - `message`: el mensaje visible, si el llamador tiene uno mejor.
 * - `detail`: el detalle técnico explícito. Nunca se enseña abierto: rutas,
 *   códigos y `error.message` crudos van plegados, para soporte.
 * - `variant="inline"`: sin caja, para cuando ya está dentro de un `Panel`.
 */
export function PanelError({
  title = "No se pudo cargar",
  error,
  message,
  detail,
  onRetry,
  variant = "bloque",
  height,
  className,
}: {
  title?: React.ReactNode;
  error?: unknown;
  message?: React.ReactNode;
  detail?: React.ReactNode;
  onRetry?: () => void;
  variant?: "bloque" | "inline";
  height?: number;
  className?: string;
}) {
  const hayError = error !== undefined && error !== null;
  const texto = message ?? (hayError ? getErrorMessage(error) : undefined);
  const tecnico = detail ?? (hayError ? detalleTecnico(error) : undefined);
  return (
    <div
      role="alert"
      className={cn(
        variant === "inline" ? "py-3" : "grid place-items-center rounded-xl border border-destructive/40 bg-card px-6 py-5",
        className,
      )}
      style={height ? { minHeight: height } : undefined}
    >
      <div className="min-w-0 max-w-[520px]">
        <div className="flex items-start gap-2">
          <CircleAlert className="mt-px h-4 w-4 flex-none text-destructive" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-tf-body font-semibold text-foreground">{title}</p>
            {texto && <p className="mt-0.5 text-tf-meta text-muted-foreground">{texto}</p>}
          </div>
        </div>
        {onRetry && (
          <Button type="button" variant="outline" size="sm" onClick={onRetry} className="ml-6 mt-3">
            <RotateCcw aria-hidden="true" />
            Reintentar
          </Button>
        )}
        {tecnico && (
          <details className="ml-6 mt-2.5 text-tf-meta text-muted-foreground">
            <summary className="w-fit cursor-pointer select-none rounded-sm hover:text-foreground">
              Detalle técnico
            </summary>
            <p className="mt-1.5 break-all font-mono text-tf-micro">{tecnico}</p>
          </details>
        )}
      </div>
    </div>
  );
}

/* ── Avisos: `Aviso` vive en `./aviso` (ver allí por qué) y se reexporta arriba. ── */

/* ── Enlace «ir a» ────────────────────────────────────────────────────── */

type EnlaceIrProps = Omit<React.ComponentProps<typeof Link>, "children" | "className"> & {
  children: React.ReactNode;
  className?: string;
};

/**
 * «Ir a» dentro de TenderFlow: texto en primario con `ArrowRight` detrás. El
 * hover solo cambia el color (se ve decenas de veces al día: no se desplaza
 * nada). La flecha es un icono con `aria-hidden`; nunca un «→» en el texto, que
 * el lector de pantalla leería. Para salir de la app, `ExternalLink`.
 */
export function EnlaceIr({ children, className, ...props }: EnlaceIrProps) {
  return (
    <Link
      {...props}
      className={cn(
        "inline-flex items-center gap-1 text-tf-meta font-medium text-primary transition-colors hover:text-foreground",
        className,
      )}
    >
      {children}
      <ArrowRight className="h-3.5 w-3.5 flex-none" aria-hidden="true" />
    </Link>
  );
}

/* ── Pestañas y conmutadores ──────────────────────────────────────────── */

// `clasePestana`, `claseContador` y `useTeclasPestanas` viven en `./pestanas` y se
// reexportan arriba: el login los usa sin cargar el resto de este módulo.

/** Los ids que unen una pestaña con su panel (`aria-controls`/`aria-labelledby`). */
function idsDePestana(idBase: string, key: string) {
  return { tab: `${idBase}-tab-${key}`, panel: `${idBase}-panel-${key}` };
}

/**
 * Los atributos del panel de la pestaña activa, cuando `PanelTabs` recibe
 * `idBase`: el lector de pantalla anuncia de qué pestaña es el contenido y
 * `aria-controls` tiene adónde apuntar.
 */
export function panelDePestana(idBase: string, key: string) {
  const ids = idsDePestana(idBase, key);
  return { role: "tabpanel", id: ids.panel, "aria-labelledby": ids.tab, tabIndex: 0 } as const;
}

/**
 * Cortes de un panel: las pestañas que sustituyen a apilar nueve gráficos uno
 * debajo de otro. Mismo gesto que el conmutador de vistas del espacio, un nivel
 * más abajo.
 *
 * Teclado del patrón de pestañas de WAI-ARIA: solo la activa está en el orden
 * de tabulación, y las flechas, Inicio y Fin mueven entre ellas y la activan.
 */
export function PanelTabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  idBase,
  className,
}: {
  tabs: { key: T; label: string; badge?: React.ReactNode }[];
  value: T;
  onChange: (next: T) => void;
  label: string;
  /** Con él, cada pestaña apunta a su panel (`panelDePestana`). */
  idBase?: string;
  className?: string;
}) {
  const claves = React.useMemo(() => tabs.map((tab) => tab.key), [tabs]);
  const { ref, onKeyDown } = useTeclasPestanas(claves, value, onChange);

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label={label}
      className={cn("flex flex-wrap items-center gap-0.5 border-b border-border/60 pb-2", className)}
    >
      {tabs.map((tab) => {
        const on = tab.key === value;
        const ids = idBase ? idsDePestana(idBase, tab.key) : null;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={ids?.tab}
            // Solo la activa: las otras no tienen panel montado, y un
            // `aria-controls` que apunta a un id inexistente es un error.
            aria-controls={on ? ids?.panel : undefined}
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onKeyDown={onKeyDown}
            onClick={() => onChange(tab.key)}
            className={clasePestana(on)}
          >
            {tab.label}
            {/* El espacio separa etiqueta y recuento en el nombre accesible
                («Cola 3», no «Cola3»); en un flex no ocupa sitio. */}
            {tab.badge != null && (
              <>
                {" "}
                <span className={claseContador(on)}>{tab.badge}</span>
              </>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Una opción de `Segmented`. */
export interface OpcionSegmented<T extends string> {
  value: T;
  label: React.ReactNode;
  /** Recuento junto a la etiqueta; forma parte del nombre accesible. */
  count?: number | string;
  icon?: LucideIcon;
  disabled?: boolean;
}

/**
 * Conmutador de modo o filtro (Cómoda/Compacta, Búsqueda/Preguntar, los
 * segmentos del Radar): botones con `aria-pressed` y la misma piel que
 * `PanelTabs`. Para pestañas con panel, `PanelTabs`; esto no promete el
 * teclado de un `tablist`, cada opción es una parada de Tab.
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
  size = "sm",
  className,
}: {
  value: T;
  onChange: (next: T) => void;
  options: readonly OpcionSegmented<T>[];
  "aria-label": string;
  /** `sm` (28 px en escritorio, por defecto) o `xs` (24 px, barras densas). */
  size?: "sm" | "xs";
  className?: string;
}) {
  return (
    <div role="group" aria-label={ariaLabel} className={cn("inline-flex flex-wrap items-center gap-0.5", className)}>
      {options.map((opcion) => {
        const on = opcion.value === value;
        const Icono = opcion.icon;
        return (
          <button
            key={opcion.value}
            type="button"
            aria-pressed={on}
            disabled={opcion.disabled}
            onClick={() => onChange(opcion.value)}
            className={cn(clasePestana(on), size === "xs" && "h-6 px-2 text-tf-micro md:h-6")}
          >
            {Icono && <Icono aria-hidden="true" />}
            {opcion.label}
            {opcion.count != null && (
              <>
                {" "}
                <span className={claseContador(on)}>{opcion.count}</span>
              </>
            )}
          </button>
        );
      })}
    </div>
  );
}
