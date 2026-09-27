import type * as React from "react";
import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/*
 * Módulo propio, y no dentro de `panel.tsx`, por peso: la puerta (login y
 * restablecer contraseña) solo necesita el aviso, y `panel.tsx` arrastra
 * `query-feedback`, `Skeleton`, `Button` y el resto del vocabulario de la
 * consola. Importado desde `panel`, `/login` pasaba de su techo de
 * `bundle-budget.json` (813 KB frente a 804). `panel.tsx` lo reexporta, así que
 * la consola sigue importándolo de `@/components/console/panel`.
 */

export type TonoAviso = "info" | "warning" | "danger" | "success";

const TONO_AVISO: Record<TonoAviso, { caja: string; icono: string; Icono: LucideIcon }> = {
  info: { caja: "border-info/30 bg-info/5", icono: "text-info", Icono: Info },
  warning: { caja: "border-warning/30 bg-warning/5", icono: "text-warning", Icono: TriangleAlert },
  danger: { caja: "border-destructive/30 bg-destructive/5", icono: "text-destructive", Icono: CircleAlert },
  success: { caja: "border-success/30 bg-success/5", icono: "text-success", Icono: CircleCheck },
};

/**
 * Banda de aviso: info, aviso, peligro o éxito. Una sola receta (borde /30,
 * fondo /5 del tono, icono de contorno del tono y texto en `foreground`) en vez
 * de las ~17 bandas escritas a mano con doce opacidades distintas.
 *
 * `role` por defecto: `alert` para `danger`, `status` para el resto; se puede
 * cambiar (`note` para una nota que no es un cambio de estado).
 * `variant="banda"` va a todo el ancho, sin radio y con solo el borde inferior
 * (debajo de una barra de herramientas).
 */
export function Aviso({
  tone = "info",
  title,
  children,
  action,
  icon,
  role,
  variant = "bloque",
  className,
}: {
  tone?: TonoAviso;
  title?: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  /** Otro icono de contorno si el del tono no dice lo bastante. */
  icon?: LucideIcon;
  role?: "status" | "alert" | "note";
  variant?: "bloque" | "banda";
  className?: string;
}) {
  const estilo = TONO_AVISO[tone];
  const Icono = icon ?? estilo.Icono;
  return (
    <div
      role={role ?? (tone === "danger" ? "alert" : "status")}
      className={cn(
        "flex items-start gap-2 px-3 py-2 text-tf-meta text-foreground",
        variant === "banda" ? "border-b" : "rounded-md border",
        estilo.caja,
        className,
      )}
    >
      <Icono className={cn("mt-px h-3.5 w-3.5 flex-none", estilo.icono)} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children != null && <div className={cn(title && "mt-0.5")}>{children}</div>}
      </div>
      {action && <div className="flex-none self-center">{action}</div>}
    </div>
  );
}
