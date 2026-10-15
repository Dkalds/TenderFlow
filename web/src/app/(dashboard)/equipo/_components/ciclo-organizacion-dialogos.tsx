"use client";

/**
 * Las tres confirmaciones del ciclo de una organización: salir, traspasar y
 * borrar. Cada diálogo monta su contenido al abrirse, así que una apertura no
 * hereda el error de la anterior; cuando la API se niega, su motivo se pinta
 * dentro, junto al botón que lo provocó.
 */

import * as React from "react";
import { Aviso } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { Organization, OrganizationMember } from "@/hooks/use-organization";
import { getErrorMessage } from "@/lib/query-feedback";
import { pideReautenticacion } from "@/lib/reautenticacion";
import {
  type ResumenDeBorrado,
  useBorrarOrganizacion,
  useSalirDeOrganizacion,
  useTraspasarPropiedad,
  useVistaPreviaBorrado,
} from "../_hooks/use-ciclo-organizacion";

const ANCHO = "w-[min(32rem,calc(100vw-2rem))] p-5";

function ErrorDelCiclo({ error, accion }: { error: unknown; accion: string }) {
  if (pideReautenticacion(error)) return <AvisoReautenticacion accion={accion} />;
  return <Aviso tone="danger">{getErrorMessage(error, "accion")}</Aviso>;
}

function Botonera({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex justify-end gap-2">
      <DialogClose asChild>
        <Button type="button" variant="ghost" size="sm">
          Cancelar
        </Button>
      </DialogClose>
      {children}
    </div>
  );
}

interface DialogoProps {
  organizacion: Organization;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SalirDialog({ organizacion, open, onOpenChange }: DialogoProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={ANCHO}>
        <DialogTitle>¿Salir de {organizacion.name}?</DialogTitle>
        <DialogDescription className="mt-1">
          Dejarás de verla desde este momento. Para volver, su propietario o un administrador tendrá que invitarte de nuevo.
        </DialogDescription>
        <ConfirmarSalida organizacion={organizacion} onHecho={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function ConfirmarSalida({ organizacion, onHecho }: { organizacion: Organization; onHecho: () => void }) {
  const salir = useSalirDeOrganizacion(organizacion);
  return (
    <div className="mt-4 flex flex-col gap-4">
      {salir.error ? <ErrorDelCiclo error={salir.error} accion="salir de la organización" /> : null}
      <Botonera>
        <Button size="sm" variant="destructive" disabled={salir.isPending} onClick={() => salir.mutate(undefined, { onSuccess: onHecho })}>
          Salir
        </Button>
      </Botonera>
    </div>
  );
}

export function TraspasarDialog({
  organizacion,
  destino,
  open,
  onOpenChange,
}: DialogoProps & { destino: OrganizationMember }) {
  const persona = destino.display_name ?? destino.email ?? `Usuario ${destino.user_id}`;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={ANCHO}>
        <DialogTitle>¿Traspasar {organizacion.name}?</DialogTitle>
        <DialogDescription className="mt-1">
          {persona} pasará a ser propietario y tú quedarás como administrador. Solo el nuevo propietario podrá volver a
          traspasarla o borrarla.
        </DialogDescription>
        <ConfirmarTraspaso organizacion={organizacion} destino={destino} onHecho={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function ConfirmarTraspaso({
  organizacion,
  destino,
  onHecho,
}: {
  organizacion: Organization;
  destino: OrganizationMember;
  onHecho: () => void;
}) {
  const traspasar = useTraspasarPropiedad(organizacion);
  return (
    <div className="mt-4 flex flex-col gap-4">
      {traspasar.error ? <ErrorDelCiclo error={traspasar.error} accion="traspasar la propiedad" /> : null}
      <Botonera>
        <Button
          size="sm"
          disabled={traspasar.isPending}
          onClick={() => traspasar.mutate(destino.user_id, { onSuccess: onHecho })}
        >
          Traspasar la propiedad
        </Button>
      </Botonera>
    </div>
  );
}

/** «14 oportunidades», «1 comentario»; un -1 es que no se pudo contar, nunca cero. */
function recuento(n: number, singular: string, plural: string): string {
  if (n < 0) return `${plural}: no se pudieron contar`;
  return `${n} ${n === 1 ? singular : plural}`;
}

function miembros(n: number): string {
  if (n < 0) return "Miembros: no se pudieron contar";
  if (n <= 1) return "Solo tú pierdes el acceso";
  return `${n} miembros, tú incluido, pierden el acceso`;
}

function LoQueSeBorra({ resumen }: { resumen: ResumenDeBorrado }) {
  return (
    <ul aria-label="Lo que se borra" className="list-disc space-y-0.5 pl-5 text-tf-body">
      <li>{recuento(resumen.oportunidades ?? 0, "oportunidad", "oportunidades")}</li>
      <li>{recuento(resumen.comentarios ?? 0, "comentario", "comentarios")}</li>
      <li>{recuento(resumen.adjuntos ?? 0, "adjunto", "adjuntos")}</li>
      <li>{miembros(resumen.miembros ?? 0)}</li>
    </ul>
  );
}

export function BorrarDialog({ organizacion, open, onOpenChange }: DialogoProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={ANCHO}>
        <DialogTitle>¿Borrar {organizacion.name}?</DialogTitle>
        <DialogDescription className="mt-1">
          Se borra para todo el equipo y no se puede deshacer. Lo personal de cada miembro —perfil, favoritos, reglas—
          se queda en su cuenta.
        </DialogDescription>
        <ConfirmarBorrado organizacion={organizacion} onHecho={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function ConfirmarBorrado({ organizacion, onHecho }: { organizacion: Organization; onHecho: () => void }) {
  const vistaPrevia = useVistaPreviaBorrado(organizacion.id, true);
  const borrar = useBorrarOrganizacion(organizacion);
  const [nombre, setNombre] = React.useState("");
  const id = React.useId();
  // El nombre exacto, y no un «sí»: con dos pestañas y dos organizaciones
  // parecidas, obliga a mirar cuál se está borrando.
  const coincide = nombre.trim() === organizacion.name.trim();

  return (
    <div className="mt-4 flex flex-col gap-4">
      {vistaPrevia.isLoading ? (
        <Skeleton className="h-20 w-full rounded-md" />
      ) : vistaPrevia.data ? (
        <LoQueSeBorra resumen={vistaPrevia.data} />
      ) : (
        <Aviso tone="danger">
          No se pudo calcular lo que se borraría, y no se borra a ciegas. {getErrorMessage(vistaPrevia.error)}
        </Aviso>
      )}
      <Field
        htmlFor={`${id}-nombre`}
        label={
          <>
            Escribe <strong>{organizacion.name}</strong> para confirmar
          </>
        }
      >
        <Input
          id={`${id}-nombre`}
          value={nombre}
          onChange={(evento) => setNombre(evento.target.value)}
          autoComplete="off"
        />
      </Field>
      {borrar.error ? <ErrorDelCiclo error={borrar.error} accion="borrar la organización" /> : null}
      <Botonera>
        <Button
          size="sm"
          variant="destructive"
          disabled={!coincide || !vistaPrevia.data || borrar.isPending}
          onClick={() => borrar.mutate(undefined, { onSuccess: onHecho })}
        >
          Borrar definitivamente
        </Button>
      </Botonera>
    </div>
  );
}
