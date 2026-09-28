"use client";

/**
 * Ficha de una cuenta: el cliente, sus órganos y qué pasa con él.
 *
 * Es la mitad de F1.5 que la primera versión no construyó: «marcar un órgano
 * como cuenta objetivo **y abrir su vista**». Responde a la pregunta de quien
 * trabaja cuentas —«¿qué hay con este cliente y qué toca ahora?»— en cuatro
 * bloques: lo que ha publicado, los contratos que vencen con quién los tiene,
 * lo que el equipo tiene abierto con él y el análisis de cada órgano.
 *
 * Las cifras las calcula la API y cada bloque declara su universo y su
 * ventana (ADR-014). La cabecera sigue la forma de la ficha de oportunidad:
 * identidad arriba, acciones a la derecha, cerrar vuelve a la lista.
 */

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Pencil, Trash2, X } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { PanelError, ROTULO_DATO } from "@/components/console/panel";
import { EtiquetaChips, EtiquetasEditor } from "@/components/etiquetas/etiquetas-objeto";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import { useFichaCuenta } from "@/hooks/use-cuentas";
import { usePuedeEscribir } from "@/hooks/use-organization";
import { cn } from "@/lib/utils";

import { EditarCuentaDialog } from "../_components/editar-cuenta-dialog";
import { useBajaConDeshacer } from "../_hooks/use-baja-con-deshacer";
import { AnalisisOrgano } from "./_components/analisis-organo";
import { BloqueOportunidades, BloquePublicaciones, BloqueVencimientos } from "./_components/bloques";
import { FichaCuentaEsqueleto } from "./_components/ficha-esqueleto";
import { OrganosCuenta } from "./_components/organos-cuenta";

function cuentaIdDe(parametro: string | undefined): number | null {
  const id = Number(parametro);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export default function FichaCuentaPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const cuentaId = cuentaIdDe(params.id);
  const { data: ficha, isPending, error, refetch } = useFichaCuenta(cuentaId);
  const puedeEscribir = usePuedeEscribir();
  const objetoId = cuentaId != null ? String(cuentaId) : "";
  const etiquetas = useEtiquetasDe("cuenta", objetoId ? [objetoId] : []);
  const { dejarDeSeguir, pendiente } = useBajaConDeshacer();
  const [editando, setEditando] = React.useState(false);

  if (cuentaId == null) {
    return (
      <div className="grid h-full place-items-center p-10">
        <PanelError title="Esa cuenta no existe" message="El enlace no es de ninguna cuenta." />
      </div>
    );
  }

  if (isPending) return <FichaCuentaEsqueleto />;

  if (error || !ficha) {
    return (
      <div className="grid h-full place-items-center p-10">
        <PanelError
          title="No se pudo abrir esta cuenta"
          error={error}
          message={error ? undefined : "No existe o ya no está disponible."}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  const { cuenta } = ficha;
  const aplicadas = etiquetas.data?.[objetoId];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex-none border-b border-border/60 bg-card px-4 py-3.5">
        {/* `flex-wrap`: en una pantalla estrecha las acciones bajan de línea
            en vez de salirse por la derecha. */}
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-[12rem] flex-1">
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              <Link
                href="/cuentas"
                className={cn(ROTULO_DATO, "transition-colors hover:text-foreground")}
              >
                Cuentas
              </Link>
              <EtiquetaChips etiquetas={aplicadas} />
              {puedeEscribir && (
                <EtiquetasEditor
                  objetoTipo="cuenta"
                  objetoId={objetoId}
                  aplicadas={aplicadas}
                  descripcion={cuenta.nombre}
                />
              )}
            </div>
            <h1 className="font-display max-w-[74ch] text-tf-title font-semibold text-pretty">
              {cuenta.nombre}
            </h1>
            {cuenta.nota && (
              <p className="mt-1 max-w-[74ch] text-tf-body text-muted-foreground">{cuenta.nota}</p>
            )}
          </div>

          <div className="flex flex-none flex-wrap items-center gap-1">
            {puedeEscribir && (
              <>
                <Button variant="ghost" size="sm" onClick={() => setEditando(true)}>
                  <Pencil aria-hidden="true" />
                  Editar
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={pendiente}
                  onClick={() =>
                    dejarDeSeguir(
                      cuenta,
                      (aplicadas ?? []).map((etiqueta) => etiqueta.id),
                      () => router.push("/cuentas"),
                    )
                  }
                >
                  <Trash2 aria-hidden="true" />
                  Dejar de seguir
                </Button>
              </>
            )}
            <Link
              href="/cuentas"
              aria-label="Cerrar la ficha"
              className={buttonVariants({
                variant: "ghost",
                size: "icon-sm",
                className: "ml-2 flex-none text-muted-foreground",
              })}
            >
              <X aria-hidden="true" />
            </Link>
          </div>
        </div>
      </header>

      {/* `relative`, como el cuerpo de `SpaceShell`: el «Quitar» de cada órgano
          lleva un `sr-only` absoluto que, sin él, colgaría de `#main-content` y
          no de esta caja; con muchos órganos, `#main-content` scrollearía
          también. */}
      <div className="relative min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-8">
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-w-0 flex-col gap-3.5">
            <BloquePublicaciones bloque={ficha.publicaciones} />
            <BloqueVencimientos bloque={ficha.vencimientos} />
          </div>
          <aside className="flex min-w-0 flex-col gap-3.5">
            <OrganosCuenta cuenta={cuenta} puedeEscribir={puedeEscribir} />
            <BloqueOportunidades bloque={ficha.oportunidades} />
          </aside>
          <div className="min-w-0 xl:col-span-2">
            <AnalisisOrgano organos={cuenta.organos ?? []} />
          </div>
        </div>
      </div>

      {puedeEscribir && (
        <EditarCuentaDialog cuenta={cuenta} open={editando} onOpenChange={setEditando} />
      )}
    </div>
  );
}
