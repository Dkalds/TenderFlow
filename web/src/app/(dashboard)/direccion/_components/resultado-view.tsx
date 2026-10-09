"use client";

/**
 * F4.2 — Resultado: qué se ganó, dónde y si vamos mejor o peor.
 *
 * El orden es el de la lectura de un lunes: las cuatro cifras con su periodo
 * anterior; lo que viene (previsión) junto a por qué perdemos; dónde ganamos
 * (cuatro cortes); si el Radar ordena bien; y lo que falta por registrar.
 *
 * Tres estados de base, en vez de un hueco por panel:
 * - **Sin base en el histórico** (`cierres_historico < n_minimo`): un único
 *   aviso con las presentadas sin resultado. Las cifras de pipeline sí se
 *   enseñan —no dependen de los cierres—.
 * - **Sin base en el periodo** pero sí en el histórico: lo dice y ofrece el
 *   histórico, en vez de cuatro cortes vacíos.
 * - Con base: la pantalla entera.
 */
import Link from "next/link";

import { PanelError } from "@/components/console/panel";
import { PeriodoSelector } from "@/components/console/periodo-selector";
import type { OrganizacionActiva } from "@/hooks/use-organization";
import { ApiError } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { etiquetaPeriodo } from "@/lib/periodo";
import { formatDate } from "@/lib/utils";
import { useCuadroDireccion } from "../_hooks/use-cuadro-direccion";
import { CortesDireccion } from "./cortes-direccion";
import { DireccionEsqueleto } from "./direccion-esqueleto";
import { PendientesResultado, PocosCierresEnVentana, SinBaseDireccion } from "./pendientes-direccion";
import { PerdidasDireccion } from "./perdidas-direccion";
import { PrevisionDireccion } from "./prevision-direccion";
import { RadarDireccion } from "./radar-direccion";
import { SinPermisoDireccion } from "./sin-permiso";
import { TarjetasDireccion } from "./tarjetas-direccion";

type Cuadro = Schemas["CuadroDireccion"];

/** «Cierres desde el 9 oct 2025 · frente al mismo periodo de hace un año». */
function Ventana({ cuadro }: { cuadro: Cuadro | undefined }) {
  if (!cuadro?.periodo_desde) {
    return <>Cierres de todo el histórico, sin periodo con el que comparar</>;
  }
  const desde = formatDate(cuadro.periodo_desde);
  const hasta = cuadro.periodo_hasta ? formatDate(cuadro.periodo_hasta) : "hoy";
  return (
    <>
      Cierres del {desde} a {hasta}
      {cuadro.anterior_desde ? " · frente al mismo periodo de hace un año" : null}
    </>
  );
}

function Contenido({ cuadro, onVerHistorico }: { cuadro: Cuadro; onVerHistorico: () => void }) {
  const minimo = cuadro.n_minimo ?? 5;
  const sinBaseHistorica = (cuadro.cierres_historico ?? 0) < minimo;
  const sinBaseVentana = !sinBaseHistorica && (cuadro.cierres ?? 0) < minimo;
  const tarjetas = cuadro.tarjetas ?? [];

  if (sinBaseHistorica) {
    // Sólo la foto de hoy tiene algo que decir: el pipeline no depende de cierres.
    const pipeline = tarjetas.filter((tarjeta) => tarjeta.depende_del_periodo === false);
    return (
      <>
        <SinBaseDireccion cuadro={cuadro} />
        <PendientesResultado cuadro={cuadro} titulo="Lo que falta por registrar" />
        <TarjetasDireccion tarjetas={pipeline} />
        <PrevisionDireccion cuadro={cuadro} />
      </>
    );
  }

  return (
    <>
      <TarjetasDireccion tarjetas={tarjetas} />
      <div className="grid gap-6 lg:grid-cols-2">
        <PrevisionDireccion cuadro={cuadro} />
        <PerdidasDireccion cuadro={cuadro} />
      </div>
      {sinBaseVentana ? (
        <PocosCierresEnVentana cuadro={cuadro} onVerHistorico={onVerHistorico} />
      ) : (
        <CortesDireccion cortes={cuadro.cortes ?? []} minimo={minimo} />
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <RadarDireccion cuadro={cuadro} />
        <PendientesResultado cuadro={cuadro} />
      </div>
    </>
  );
}

export function ResultadoView({ organizationId }: { organizationId: OrganizacionActiva }) {
  const { periodo, cambiarPeriodo, data, isPending, isError, error, refetch, isPlaceholderData } =
    useCuadroDireccion(organizationId);

  if (isError) {
    // 403 es «tu rol no llega»; cualquier otro fallo es un fallo. Enseñarlo todo
    // como problema de permisos mandaba a un propietario a pelearse con un rol
    // correcto mientras la API estaba caída, y hacía invisible la caída.
    return error instanceof ApiError && error.status === 403 ? (
      <SinPermisoDireccion />
    ) : (
      <PanelError title="No se ha podido cargar Dirección" error={error} onRetry={() => void refetch()} />
    );
  }
  if (isPending) return <DireccionEsqueleto />;

  return (
    <div className="flex flex-col gap-6" aria-busy={isPlaceholderData || undefined}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-tf-meta text-muted-foreground">
          <span className="sr-only">{etiquetaPeriodo(periodo)}. </span>
          <span className="font-medium text-foreground">
            <Ventana cuadro={data} />
          </span>
          {" · "}
          <Link href="/oportunidades?vista=rendimiento" className="text-primary hover:underline">
            Embudo completo en Rendimiento
          </Link>
        </p>
        <PeriodoSelector periodo={periodo} onChange={cambiarPeriodo} />
      </div>
      <div className={isPlaceholderData ? "flex flex-col gap-6 opacity-60" : "flex flex-col gap-6"}>
        <Contenido cuadro={data} onVerHistorico={() => cambiarPeriodo("historico")} />
      </div>
    </div>
  );
}
