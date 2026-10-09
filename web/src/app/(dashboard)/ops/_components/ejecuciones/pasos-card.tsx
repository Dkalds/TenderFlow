"use client";

/**
 * Los pasos del cierre post-ingesta, en el orden en que corren.
 *
 * El orden es el del cierre —lo manda la API— y no «los rotos primero»: las
 * dependencias se leen de arriba abajo, así que el paso que falló sale antes
 * que los que arrastró. Cuántos están rotos ahora lo dice el aviso de arriba.
 *
 * «No tocaba» es un resultado, no un fallo: el paso tiene cadencia propia (un
 * digest diario dentro de una pasada que corre cada cuatro horas) o su flag
 * está apagado. Pintarlo como error enseñaría a ignorar el rojo.
 */

import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Pista } from "@/components/ui/pista";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn, formatDateTime, formatNumber } from "@/lib/utils";
import type { EjecucionesResumen, PasoEjecucion } from "../../_hooks/use-ejecuciones";

type Estado = PasoEjecucion["ultimo_estado"];

const INSIGNIA: Record<Estado, { texto: string; variant: "success" | "destructive" | "neutral" | "warning" }> = {
  ok: { texto: "Bien", variant: "success" },
  error: { texto: "Error", variant: "destructive" },
  omitido: { texto: "No tocaba", variant: "neutral" },
  omitido_por_dependencia: { texto: "Arrastrado", variant: "warning" },
  sin_ejecuciones: { texto: "Sin ejecuciones", variant: "neutral" },
};

const PISTA_ESTADO: Partial<Record<Estado, string>> = {
  omitido: "El paso decidió no correr: su cadencia aún no vencía o su flag está apagado.",
  omitido_por_dependencia: "No llegó a correr porque falló un paso del que depende.",
};

const TIER: Record<string, string> = {
  bloqueante: "Bloqueante",
  advisory: "Informativo",
};

const CELDA = "px-3 py-2.5 align-top";

function fecha(valor: string | null | undefined): string {
  return valor ? formatDateTime(valor) : "—";
}

function FilaPaso({ paso }: { paso: PasoEjecucion }) {
  const insignia = INSIGNIA[paso.ultimo_estado];
  const roto = paso.ultimo_estado === "error";

  return (
    <tr className={cn("border-b border-border/60 last:border-0", roto && "bg-destructive/5")}>
      <td className={CELDA}>
        <span className="font-mono text-tf-body">{paso.paso}</span>
        {/* El último error se enseña mientras el paso lo arrastre en la
            ventana, aunque la última ejecución ya fuera bien: es lo que
            explica el recuento de la derecha. En ese caso va con su fecha,
            que no sale en ninguna columna: sin ella, el error de un incidente
            cerrado se lee como un fallo de ahora. Con el paso roto no hace
            falta, es la de «Última ejecución». */}
        {paso.ultimo_error && (roto || paso.fallos > 0) && (
          <>
            {!roto && paso.ultimo_fallo && (
              <p className="tf-tnum mt-0.5 text-tf-meta text-muted-foreground">
                Último fallo: {formatDateTime(paso.ultimo_fallo)}
              </p>
            )}
            <Pista contenido={paso.ultimo_error}>
              <p className="mt-0.5 line-clamp-2 max-w-prose text-tf-meta text-muted-foreground">
                {paso.ultimo_error}
              </p>
            </Pista>
          </>
        )}
      </td>
      <td className={cn(CELDA, "text-tf-meta text-muted-foreground")}>
        {paso.tier ? (TIER[paso.tier] ?? paso.tier) : "Retirado"}
      </td>
      <td className={CELDA}>
        <Pista contenido={PISTA_ESTADO[paso.ultimo_estado]}>
          <Badge size="sm" variant={insignia.variant}>
            {insignia.texto}
          </Badge>
        </Pista>
      </td>
      <td className={cn(CELDA, "tf-tnum whitespace-nowrap text-tf-meta text-muted-foreground")}>
        {fecha(paso.ultima_ejecucion)}
      </td>
      <td className={cn(CELDA, "tf-tnum whitespace-nowrap text-tf-meta text-muted-foreground")}>
        {fecha(paso.ultima_ok)}
      </td>
      <td className={cn(CELDA, "tf-tnum whitespace-nowrap text-right")}>
        {paso.ejecuciones === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className={cn("font-medium", paso.fallos > 0 && "text-destructive")}>
            {formatNumber(paso.fallos)} de {formatNumber(paso.ejecuciones)}
          </span>
        )}
      </td>
    </tr>
  );
}

export function PasosCard({ resumen }: { resumen: EjecucionesResumen }) {
  const pasos = resumen.pasos ?? [];
  const rotos = resumen.pasos_en_error;

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Pasos del cierre"
        hint={`En el orden en que corren. Fallos de los últimos ${resumen.ventana_dias} días.`}
      />
      <Aviso tone={rotos > 0 ? "danger" : "success"} className="mb-4">
        {rotos > 0
          ? `${formatNumber(rotos)} ${rotos === 1 ? "paso falló" : "pasos fallaron"} en su última ejecución`
          : "Ningún paso falló en su última ejecución"}
      </Aviso>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-tf-body">
          <caption className="sr-only">Pasos del cierre post-ingesta y su última ejecución</caption>
          <thead className="border-y border-border/70">
            <tr>
              <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                Paso
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                Tipo
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                Último resultado
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                Última ejecución
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                Última vez bien
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2 text-right")}>
                Fallos
              </th>
            </tr>
          </thead>
          <tbody>
            {pasos.map((paso) => (
              <FilaPaso key={paso.paso} paso={paso} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-tf-meta text-muted-foreground">
        «Sin ejecuciones» significa que el paso no ha dejado ninguna fila en {resumen.horizonte_dias} días.
        Un paso bloqueante que falla pone la pasada en rojo; uno informativo avisa y no la detiene.
      </p>
    </Panel>
  );
}
