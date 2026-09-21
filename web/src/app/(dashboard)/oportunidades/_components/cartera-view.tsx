"use client";

/**
 * Cartera — contratos ganados que siguen en ejecución (F4.3).
 *
 * Vista `?vista=cartera` de Oportunidades. Hasta 2026-09-20 vivía en Mi
 * Pipeline; está aquí porque es la continuación de una oportunidad ganada, y
 * las oportunidades propias se trabajan en este espacio. El `?vista=cartera`
 * viejo de `/mi-pipeline` reenvía aquí con su ámbito.
 *
 * `won` dejaba de existir para el producto justo cuando empieza lo que decide
 * si se renueva. Esta vista enseña, por contrato, la fecha de fin efectiva
 * (con **de dónde sale**: publicada, estimada por duración o movida por una
 * prórroga), las prórrogas aplicadas y la ventana en que se espera la
 * relicitación — que es una estimación de dominio y se presenta como
 * intervalo, no como fecha.
 *
 * Tres planos, de fuera adentro:
 *
 * 1. **La franja de KPIs** (`GET /pursuits/cartera/resumen`) habla de la
 *    cartera entera: no se suma en cliente y no la recortan los filtros. Es el
 *    universo del que la tabla enseña un trozo (ADR-014).
 * 2. **La tabla** es el trabajo: qué se acaba, cuánto vale y qué renovación
 *    falta. Sus filtros declaran cuántas filas quedan de cuántas.
 * 3. **El inspector** —el reparto del Radar y de la Agenda— es el contrato
 *    seleccionado con su cronología. Lo accionable sigue en la fila; lo que el
 *    inspector añade es lectura.
 *
 * «Preparar renovación» crea la oportunidad de la relicitación enlazada al
 * contrato (`POST /pursuits/cartera/{id}/renovacion`). Pide el expediente de
 * la relicitación porque la oportunidad es sobre **ese** expediente: el del
 * contrato vigente ya tiene la suya, la ganada. Cuando un contrato ya tiene
 * oportunidad de renovación, se enlaza en vez de ofrecer el botón.
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Briefcase } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Panel, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { useCartera, useCarteraResumen } from "@/hooks/use-cartera";
import { registrarEvento } from "@/lib/analytics";
import { filtrarCartera, opcionesCartera } from "@/lib/cartera";
import { CarteraFila } from "./cartera/cartera-fila";
import { CarteraFiltros, TODOS } from "./cartera/cartera-filtros";
import { CarteraInspector } from "./cartera/cartera-inspector";
import { CarteraKpis } from "./cartera/cartera-kpis";

export default function CarteraView() {
  const { data, isPending, error, refetch } = useCartera();
  const resumen = useCarteraResumen();
  const params = useSearchParams();
  const [tecnologia, setTecnologia] = React.useState<string>(TODOS);
  const [organo, setOrgano] = React.useState<string>(TODOS);
  // El contrato del inspector se guarda por id y no por objeto: así un refetch
  // de la cartera —o un filtro que esconda su fila— no deja el panel pintando
  // una copia vieja. Se resuelve contra la lista en cada render y, si ya no
  // está, el inspector vuelve a pedir que se elija uno.
  const [seleccionId, setSeleccionId] = React.useState<number | null>(null);

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
  if (isPending) return <PanelLoading height={320} />;

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
  const seleccionado = visibles.find((contrato) => contrato.id === seleccionId) ?? null;

  return (
    <div className="space-y-4">
      <CarteraKpis resumen={resumen.data} cargando={resumen.isPending} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Panel className="min-w-0">
          <PanelTitle
            title="Contratos en ejecución"
            hint={`${visibles.length} de ${contratos.length} contratos ganados`}
            actions={
              <CarteraFiltros
                opciones={opciones}
                tecnologia={tecnologia}
                organo={organo}
                onTecnologia={setTecnologia}
                onOrgano={setOrgano}
              />
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
                  {/* La columna de selección sólo existe donde existe el
                      inspector (≥ xl); ver `cartera-fila.tsx`. */}
                  <TableHead className="hidden w-16 xl:table-cell">
                    <span className="sr-only">Detalle del contrato</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibles.map((contrato) => (
                  <CarteraFila
                    key={contrato.id}
                    contrato={contrato}
                    activo={contrato.id === seleccionId}
                    onSeleccionar={() => setSeleccionId(contrato.id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </Panel>

        <CarteraInspector contrato={seleccionado} />
      </div>
    </div>
  );
}
