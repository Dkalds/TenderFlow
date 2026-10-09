"use client";

/**
 * La cabecera de la vista: qué dice la API de sí misma, cuándo lo dijo y si el
 * esquema de la base de datos va con el código.
 *
 * Es el único sitio de la vista que da el veredicto. Había tres más —una fila
 * con un punto de color, la hora repetida y el icono de la tarjeta de abajo— y
 * los cuatro leían «hay respuesta» como «todo va bien».
 *
 * La tercera celda era «Versión de la API», que la respuesta no trae: salía
 * siempre con una raya. El esquema sí viaja, y es lo que de verdad se
 * desalinea tras un despliegue con la migración sin aplicar.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatDate, formatTime } from "@/lib/utils";
import type { ComponenteSalud, EstadoGlobalSalud } from "./health-checks";

const VALOR: Record<EstadoGlobalSalud, string> = {
  ok: "En línea",
  degradado: "Degradada",
  error: "Sin conexión",
  comprobando: "—",
};

const TONO: Record<EstadoGlobalSalud, "success" | "warning" | "destructive" | undefined> = {
  ok: "success",
  degradado: "warning",
  error: "destructive",
  comprobando: undefined,
};

function pistaEstado(estado: EstadoGlobalSalud, componentes: ComponenteSalud[]): string | undefined {
  if (estado === "ok") return "Todos los servicios responden";
  if (estado === "error") return "La API no responde";
  if (estado === "degradado") {
    const tocados = componentes.filter((c) => c.estado === "aviso" || c.estado === "error");
    return tocados.length
      ? `Revisa: ${tocados.map((c) => c.nombre).join(", ")}`
      : "La API se declara degradada";
  }
  return undefined;
}

/** «ok (v146_…)» → la revisión entre paréntesis, que es lo que se busca en Alembic. */
function revision(detalle: string): string | undefined {
  return /\(([^)]+)\)/.exec(detalle)?.[1];
}

export interface SaludKpisProps {
  estado: EstadoGlobalSalud;
  componentes: ComponenteSalud[];
  /** Momento del último health que llegó; `null` mientras no haya ninguno. */
  lastCheck: Date | null;
}

export function SaludKpis({ estado, componentes, lastCheck }: SaludKpisProps) {
  const cargando = estado === "comprobando";
  const esquema = componentes.find((c) => c.clave === "schema_revision");

  return (
    <StatStrip columns={3}>
      <StatCell
        label="Estado de la API"
        value={VALOR[estado]}
        hint={pistaEstado(estado, componentes)}
        tono={TONO[estado]}
        loading={cargando}
      />
      <StatCell
        label="Último chequeo"
        value={lastCheck ? formatTime(lastCheck) : "—"}
        hint={lastCheck ? formatDate(lastCheck) : undefined}
        loading={cargando}
      />
      <StatCell
        label="Esquema de la base de datos"
        value={
          !esquema || esquema.estado === "sin_dato"
            ? "—"
            : esquema.estado === "ok"
              ? "Al día"
              : "Desalineado"
        }
        hint={
          !esquema || esquema.estado === "sin_dato"
            ? "sin dato"
            : (revision(esquema.detalle) ?? esquema.detalle)
        }
        tono={esquema && esquema.estado !== "ok" && esquema.estado !== "sin_dato" ? "warning" : undefined}
        loading={cargando}
      />
    </StatStrip>
  );
}
