"use client";

/**
 * La cartera de cuentas del equipo, con lo que pasa hoy en cada una.
 *
 * La primera versión era una lista de nombres: decía a quién se seguía y nada
 * de qué pasaba con ellos. Cada fila trae ahora cuatro cifras —licitaciones
 * abiertas, última publicación, contratos que vencen y oportunidades
 * activas— que calcula el backend (`GET /cuentas/resumen`, ADR-014) con su
 * universo y su ventana, que se explican debajo de la tabla.
 *
 * El resumen llega aparte de la lista: es más caro, y la lista se pinta sin
 * esperarlo. Una cifra que no ha llegado es un esqueleto, no un cero.
 */

import * as React from "react";
import Link from "next/link";
import { Building2, Pencil, Trash2 } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EtiquetaChips, EtiquetasEditor } from "@/components/etiquetas/etiquetas-objeto";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import {
  useCuentas,
  useCuentasResumen,
  type Cuenta,
  type CuentaResumen,
  type CuentasResumen,
} from "@/hooks/use-cuentas";
import { formatDate, formatNumber } from "@/lib/utils";

import { EditarCuentaDialog } from "./editar-cuenta-dialog";
import { useBajaConDeshacer } from "../_hooks/use-baja-con-deshacer";

function Cifra({ valor, cargando }: { valor: React.ReactNode; cargando: boolean }) {
  if (cargando) return <Skeleton className="ml-auto h-4 w-8" />;
  return <span className="tabular-nums">{valor}</span>;
}

function Organos({ cuenta }: { cuenta: Cuenta }) {
  const organos = cuenta.organos ?? [];
  // Una cuenta de un órgano que se llama como él no necesita repetirlo.
  if (organos.length === 1 && organos[0].organo_nombre === cuenta.nombre) return null;
  if (organos.length === 1) {
    return <span className="block truncate text-xs text-muted-foreground">{organos[0].organo_nombre}</span>;
  }
  return <span className="block text-xs text-muted-foreground">{organos.length} órganos</span>;
}

function QueCuentan({ resumen }: { resumen: CuentasResumen }) {
  const filas: { cifra: string; ambito: CuentasResumen["ambito_abiertas"] }[] = [
    { cifra: "Abiertas", ambito: resumen.ambito_abiertas },
    { cifra: "Última publicación", ambito: resumen.ambito_ultima_publicacion },
    { cifra: "Vencen", ambito: resumen.ambito_vencen },
    { cifra: "Oportunidades", ambito: resumen.ambito_oportunidades },
  ];
  return (
    <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none font-medium text-foreground">
        Qué cuentan estas cifras
      </summary>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">
        {filas.map(({ cifra, ambito }) => (
          <div key={cifra}>
            <dt className="font-medium text-foreground">{cifra}</dt>
            <dd>
              {ambito.ventana} {ambito.universo}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function ListaCuentas({
  puedeEscribir,
  onNueva,
}: {
  puedeEscribir: boolean;
  onNueva?: () => void;
}) {
  const { data, isLoading, isError, refetch } = useCuentas();
  const resumen = useCuentasResumen();
  const { dejarDeSeguir, pendiente } = useBajaConDeshacer();
  const [editando, setEditando] = React.useState<Cuenta | null>(null);
  const cuentas = data ?? [];
  // F1.6 — etiquetas de todas las cuentas en una sola petición, y de la misma
  // organización que las cuentas: hasta 2026-09-25 la lista salía de la
  // personal y las etiquetas de la activa.
  const etiquetas =
    useEtiquetasDe("cuenta", cuentas.map((cuenta) => String(cuenta.id))).data ?? {};
  const porCuenta = React.useMemo(() => {
    const mapa = new Map<number, CuentaResumen>();
    for (const fila of resumen.data?.filas ?? []) mapa.set(fila.cuenta_id, fila);
    return mapa;
  }, [resumen.data]);

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (isError) {
    return (
      <EmptyState
        title="No se pudieron cargar las cuentas"
        hint="Vuelve a intentarlo en un momento."
        actionLabel="Reintentar"
        onAction={() => void refetch()}
      />
    );
  }

  if (cuentas.length === 0) {
    // Vacío declarado y con la acción al lado: una tabla en blanco se lee como
    // que la pantalla está rota, no como que todavía no hay nada.
    return (
      <EmptyState
        icon={Building2}
        title="Tu equipo todavía no sigue ninguna cuenta"
        hint="Crea una cuenta con los órganos de un cliente y todo el equipo recibirá en la campana sus publicaciones nuevas y los contratos que entren en sus últimos seis meses."
        actionLabel={onNueva ? "Nueva cuenta" : undefined}
        onAction={onNueva}
      />
    );
  }

  const cargandoCifras = resumen.isLoading;
  const sinCifras = resumen.isError;
  const cifra = (cuenta: Cuenta, campo: "abiertas" | "vencen" | "oportunidades_activas") => {
    const fila = porCuenta.get(cuenta.id);
    return sinCifras || !fila ? "—" : formatNumber(fila[campo]);
  };

  return (
    <div className="flex flex-col gap-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Cuenta</TableHead>
            <TableHead className="text-right">Abiertas</TableHead>
            <TableHead>Última publicación</TableHead>
            <TableHead className="text-right">Vencen en 12 meses</TableHead>
            <TableHead className="text-right">Oportunidades</TableHead>
            <TableHead>Etiquetas</TableHead>
            {puedeEscribir && <TableHead className="w-24 text-right">Acciones</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {cuentas.map((cuenta) => {
            const fila = porCuenta.get(cuenta.id);
            const aplicadas = etiquetas[String(cuenta.id)];
            return (
              <TableRow key={cuenta.id}>
                <TableCell className="max-w-[22rem]">
                  <Link
                    href={`/cuentas/${cuenta.id}`}
                    className="block truncate font-medium hover:underline"
                  >
                    {cuenta.nombre}
                  </Link>
                  <Organos cuenta={cuenta} />
                  {cuenta.nota && (
                    <span className="block truncate text-xs text-muted-foreground italic">
                      {cuenta.nota}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Cifra cargando={cargandoCifras} valor={cifra(cuenta, "abiertas")} />
                </TableCell>
                <TableCell>
                  {/* Sin fila no hay dato (una cuenta recién creada con el
                      resumen aún por refrescar): «—», no «sin publicaciones». */}
                  <Cifra
                    cargando={cargandoCifras}
                    valor={
                      sinCifras || !fila
                        ? "—"
                        : fila.ultima_publicacion
                          ? formatDate(fila.ultima_publicacion)
                          : "Sin publicaciones"
                    }
                  />
                </TableCell>
                <TableCell className="text-right">
                  <Cifra cargando={cargandoCifras} valor={cifra(cuenta, "vencen")} />
                </TableCell>
                <TableCell className="text-right">
                  <Cifra cargando={cargandoCifras} valor={cifra(cuenta, "oportunidades_activas")} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <EtiquetaChips etiquetas={aplicadas} />
                    {puedeEscribir && (
                      <EtiquetasEditor
                        objetoTipo="cuenta"
                        objetoId={String(cuenta.id)}
                        aplicadas={aplicadas}
                        descripcion={cuenta.nombre}
                      />
                    )}
                  </div>
                </TableCell>
                {puedeEscribir && (
                  <TableCell className="text-right whitespace-nowrap">
                    <Button variant="ghost" size="sm" onClick={() => setEditando(cuenta)}>
                      <Pencil className="size-4" aria-hidden="true" />
                      <span className="sr-only">Editar {cuenta.nombre}</span>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        dejarDeSeguir(cuenta, (aplicadas ?? []).map((etiqueta) => etiqueta.id))
                      }
                      disabled={pendiente}
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                      <span className="sr-only">Dejar de seguir {cuenta.nombre}</span>
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {resumen.data && <QueCuentan resumen={resumen.data} />}

      {editando && (
        <EditarCuentaDialog
          cuenta={editando}
          open
          onOpenChange={(abierto) => {
            if (!abierto) setEditando(null);
          }}
        />
      )}
    </div>
  );
}
