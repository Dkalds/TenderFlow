"use client";

/**
 * Cartera — contratos ganados que siguen en ejecución (F4.3).
 *
 * `won` dejaba de existir para el producto justo cuando empieza lo que decide
 * si se renueva. Esta vista enseña, por contrato, la fecha de fin efectiva
 * (con **de dónde sale**: publicada, estimada por duración o movida por una
 * prórroga), las prórrogas aplicadas y la ventana en que se espera la
 * relicitación — que es una estimación de dominio y se presenta como
 * intervalo, no como fecha.
 *
 * «Preparar renovación» no está aquí: el backend todavía no expone esa
 * acción. Cuando un contrato ya tiene oportunidad de renovación, se enlaza.
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Briefcase } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Panel, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { useCartera } from "@/hooks/use-cartera";
import { registrarEvento } from "@/lib/analytics";
import { fechaCorta } from "@/lib/adjudicacion-prevista";
import {
  filtrarCartera,
  opcionesCartera,
  origenFin,
  plazoRestante,
  urgenciaCartera,
} from "@/lib/cartera";
import { cn, formatCompactCurrency } from "@/lib/utils";

const TODOS = "todos";

function OrigenFin({ origen }: { origen: string | null | undefined }) {
  const info = origenFin(origen);
  if (!info) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`Fecha de fin ${info.texto}: ${info.explicacion}`}
          className="ml-1.5 inline-flex h-[18px] items-center rounded-sm border border-border/70 bg-muted/60 px-1.5 text-[10px] font-medium text-muted-foreground"
        >
          {info.texto}
        </button>
      </TooltipTrigger>
      <TooltipContent>{info.explicacion}</TooltipContent>
    </Tooltip>
  );
}

export default function CarteraView() {
  const { data, isLoading, error, refetch } = useCartera();
  const params = useSearchParams();
  const [tecnologia, setTecnologia] = React.useState<string>(TODOS);
  const [organo, setOrgano] = React.useState<string>(TODOS);

  const registrado = React.useRef(false);
  React.useEffect(() => {
    if (registrado.current) return;
    registrado.current = true;
    const origen = params.get("origen");
    registrarEvento("cartera_abierta", {
      origen: origen === "alerta" || origen === "rail" ? origen : "conmutador",
    });
  }, [params]);

  if (error) {
    return (
      <PanelError
        title="No se pudo cargar la cartera"
        detail={(error as Error).message}
        onRetry={() => void refetch()}
        height={320}
      />
    );
  }
  if (isLoading) return <PanelLoading height={320} />;

  const contratos = data ?? [];
  if (contratos.length === 0) {
    return (
      <EmptyState
        icon={Briefcase}
        title="Todavía no hay contratos en cartera"
        hint="Cuando una oportunidad se cierra como ganada pasa aquí, con su fecha de fin y la ventana de relicitación."
      />
    );
  }

  const opciones = opcionesCartera(contratos);
  const visibles = filtrarCartera(contratos, {
    tecnologia: tecnologia === TODOS ? null : tecnologia,
    organo: organo === TODOS ? null : organo,
  });

  return (
    <Panel>
      <PanelTitle
        title="Contratos en ejecución"
        hint={`${visibles.length} de ${contratos.length} contratos ganados`}
        actions={
          <>
            <Select value={tecnologia} onValueChange={setTecnologia}>
              <SelectTrigger className="h-7 w-40 text-xs" aria-label="Filtrar por tecnología">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={TODOS}>Todas las tecnologías</SelectItem>
                {opciones.tecnologias.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={organo} onValueChange={setOrgano}>
              <SelectTrigger className="h-7 w-48 text-xs" aria-label="Filtrar por órgano">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={TODOS}>Todos los órganos</SelectItem>
                {opciones.organos.map((o) => (
                  <SelectItem key={o} value={o}>
                    {o}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        }
      />
      {visibles.length === 0 ? (
        <p role="status" className="py-6 text-center text-[11.5px] text-muted-foreground">
          Ningún contrato con esos filtros.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Contrato</TableHead>
              <TableHead>Fin efectivo</TableHead>
              <TableHead className="text-right">Prórrogas</TableHead>
              <TableHead>Relicitación esperada</TableHead>
              <TableHead className="text-right">Adjudicado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visibles.map((contrato) => {
              const urgencia = urgenciaCartera(contrato);
              return (
                <TableRow key={contrato.id}>
                  <TableCell className="max-w-[28rem]">
                    <Link
                      href={`/oportunidades/${contrato.pursuit_id}`}
                      className="line-clamp-2 font-medium hover:underline"
                    >
                      {contrato.titulo ?? contrato.licitacion_id}
                    </Link>
                    <p className="truncate text-[10.5px] text-muted-foreground">
                      {contrato.organo_contratacion ?? "Órgano sin publicar"}
                      {contrato.tecnologia ? ` · ${contrato.tecnologia}` : null}
                    </p>
                    {contrato.renovacion_pursuit_id ? (
                      <Link
                        href={`/oportunidades/${contrato.renovacion_pursuit_id}`}
                        className="text-[10.5px] font-medium text-primary hover:underline"
                      >
                        Ver oportunidad de renovación
                      </Link>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <span className="tf-tnum whitespace-nowrap">
                      {contrato.fecha_fin_efectiva ? fechaCorta(contrato.fecha_fin_efectiva) : "—"}
                    </span>
                    <OrigenFin origen={contrato.fecha_fin_origen} />
                    <p
                      className={cn(
                        "text-[10.5px]",
                        urgencia === "vencido" || urgencia === "pronto"
                          ? "font-medium text-[hsl(var(--warning))]"
                          : "text-muted-foreground",
                      )}
                    >
                      {plazoRestante(contrato)}
                    </p>
                  </TableCell>
                  <TableCell className="tf-tnum text-right">{contrato.prorrogas_aplicadas}</TableCell>
                  <TableCell>
                    {contrato.relicitacion_desde && contrato.relicitacion_hasta ? (
                      <>
                        <span className="tf-tnum whitespace-nowrap">
                          {fechaCorta(contrato.relicitacion_desde)} –{" "}
                          {fechaCorta(contrato.relicitacion_hasta)}
                        </span>
                        <p className="text-[10.5px] text-muted-foreground">
                          Estimación: 6 a 3 meses antes del fin
                        </p>
                      </>
                    ) : (
                      <span className="text-muted-foreground">Sin fecha de fin</span>
                    )}
                  </TableCell>
                  <TableCell className="tf-tnum text-right">
                    {contrato.importe_adjudicado != null
                      ? formatCompactCurrency(contrato.importe_adjudicado)
                      : "—"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
