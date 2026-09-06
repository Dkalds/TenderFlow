"use client";

import * as React from "react";
import Link from "next/link";
import { RotateCcw } from "lucide-react";
import { cn, formatPercent } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

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
 */

export function Panel({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-border/60 bg-card/70 px-4 py-3.5", className)}
      {...props}
    >
      {children}
    </div>
  );
}

/** Título de panel: qué es, y en una línea de qué ámbito habla. */
export function PanelTitle({
  title,
  hint,
  actions,
  className,
}: {
  title: React.ReactNode;
  hint?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-baseline gap-2.5", className)}>
      <h3 className="flex-none text-[12.5px] font-semibold">{title}</h3>
      {hint && <span className="truncate text-[10.5px] text-muted-foreground">{hint}</span>}
      {actions && (
        <>
          <div className="flex-1" />
          <div className="flex flex-none items-center gap-1.5">{actions}</div>
        </>
      )}
    </div>
  );
}

/** Rótulo de sección dentro de un panel o de un inspector. */
export function SectionTitle({
  children,
  aside,
  className,
}: {
  children: React.ReactNode;
  aside?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-2.5 flex items-baseline justify-between gap-2", className)}>
      <h4 className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {children}
      </h4>
      {aside && <span className="text-[10.5px] text-muted-foreground/70">{aside}</span>}
    </div>
  );
}

/**
 * Celda de una tira de estadísticas. Los KPIs de la consola van pegados en una
 * rejilla de 1px, no en cuatro tarjetas separadas: leen como una sola fila de
 * dato en vez de como cuatro objetos que compiten.
 */
export function StatCell({
  label,
  value,
  hint,
  trend,
  trendAlert,
  badge,
  loading,
  onClick,
  href,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  trend?: number;
  /**
   * Sube el delta al cuerpo del valor y lo pinta en ámbar. Es para la celda que
   * ya viene marcada como anómala: con el delta a 11 px, la desviación que la
   * etiqueta anunciaba había que ir a buscarla — el ojo aterrizaba en el valor
   * absoluto, que es justo el número que **no** ha cambiado. El signo y el
   * color siguen saliendo del propio delta, así que una anomalía a la baja se
   * lee roja igual que antes; lo único que cambia es el tamaño.
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
  accent?: string;
}) {
  const up = (trend ?? 0) >= 0;
  const body = (
    <>
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="truncate font-mono text-[8.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </span>
        {badge}
      </div>
      {loading ? (
        <Skeleton className="h-4 w-24 rounded" />
      ) : (
        <div className="flex min-w-0 items-baseline gap-2">
          <span
            className="tf-tnum truncate font-mono text-base font-semibold leading-none"
            style={accent ? { color: accent } : undefined}
          >
            {value}
          </span>
          {trend != null && (
            <span
              className={cn(
                "tf-tnum flex-none font-mono leading-none",
                trendAlert
                  ? "text-base font-semibold text-[hsl(var(--warning))]"
                  : cn(
                      "text-[11px] font-medium",
                      up ? "text-[hsl(var(--success))]" : "text-destructive",
                    ),
              )}
            >
              {/* `formatPercent` y no `toFixed`: éste emite siempre el punto
                  decimal, así que la tira sacaba «+768.9%» pegado a un
                  «93,1%» del panel de al lado — el mismo carácter con dos
                  significados a 40 px de distancia que ya señaló el hallazgo 3
                  de la auditoría UX para el KPI bar. */}
              {up ? "+" : ""}
              {formatPercent(trend)}
            </span>
          )}
        </div>
      )}
      {hint && (
        // Sin el /80: a 10px la opacidad dejaba el hint por debajo de 4.5:1
        // sobre bg-card (violación color-contrast del E2E de accesibilidad).
        <div className="mt-1 truncate text-[10px] leading-[1.3] text-muted-foreground">{hint}</div>
      )}
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="min-w-0 bg-card px-3.5 py-2.5 text-left transition-colors duration-140 ease-out hover:bg-primary/5"
      >
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="min-w-0 bg-card px-3.5 py-2.5 text-left transition-colors duration-140 ease-out hover:bg-primary/5"
      >
        {body}
      </button>
    );
  }
  return <div className="min-w-0 bg-card px-3.5 py-2.5">{body}</div>;
}

/** Contenedor de una tira de `StatCell`, con la rejilla de 1px del sistema. */
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
        // Dos columnas por debajo de `lg` y las que pida el llamante a partir
        // de ahí: apretar seis KPIs en una pantalla de portátil los vuelve
        // ilegibles antes que compactos.
        "grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60",
        className,
      )}
      style={{ ["--console-stat-columns" as string]: String(columns) }}
    >
      {children}
    </div>
  );
}

/**
 * Los tres estados de un panel de datos, con el alto del contenido real para
 * que la página no salte cuando llega el dato.
 */
export function PanelLoading({ height = 260 }: { height?: number }) {
  return <Skeleton className="w-full rounded-lg" style={{ height }} />;
}

export function PanelEmpty({
  message,
  action,
  height,
}: {
  message: string;
  action?: React.ReactNode;
  height?: number;
}) {
  return (
    <div
      // `status` y no un div mudo: pasar de «cargando» a «no hay nada» es un
      // cambio de estado que el lector de pantalla tiene que oír, y era
      // silencioso en toda la consola (hallazgo 5 de la auditoría UX).
      role="status"
      className="grid place-items-center rounded-[10px] border border-dashed border-border/60 px-4 py-9 text-center"
      style={height ? { minHeight: height } : undefined}
    >
      <div>
        <p className="text-[11.5px] leading-[1.5] text-muted-foreground">{message}</p>
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function PanelError({
  title = "No se pudo cargar",
  detail,
  onRetry,
  height,
}: {
  title?: string;
  detail?: string;
  onRetry?: () => void;
  height?: number;
}) {
  return (
    <div
      role="alert"
      className="grid place-items-center rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
      style={height ? { minHeight: height } : undefined}
    >
      <div className="max-w-[520px]">
        <div className="mb-2 flex items-center gap-2.5">
          <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
            !
          </span>
          <span className="text-[13.5px] font-semibold text-destructive">{title}</span>
        </div>
        {detail && (
          <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">{detail}</p>
        )}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="tf-pressable inline-flex h-[30px] items-center gap-1.5 rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <RotateCcw className="h-3 w-3" aria-hidden="true" />
            Reintentar
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Cortes de un panel: las pestañas que sustituyen a apilar nueve gráficos uno
 * debajo de otro. Mismo gesto que el conmutador de vistas del espacio, un nivel
 * más abajo.
 */
export function PanelTabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { key: T; label: string; badge?: React.ReactNode }[];
  value: T;
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex flex-wrap items-center gap-0.5 border-b border-border/50 pb-2"
    >
      {tabs.map((tab) => {
        const on = tab.key === value;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(tab.key)}
            className={cn(
              "tf-pressable inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 text-[12px] font-medium transition-colors duration-150 ease-out",
              on
                ? "border-border/70 bg-secondary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
            {tab.badge != null && (
              <span
                className={cn(
                  "tf-tnum rounded px-1 py-0.5 font-mono text-[9px] font-medium",
                  on ? "bg-primary/16 text-primary" : "bg-muted-foreground/12 text-muted-foreground",
                )}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
