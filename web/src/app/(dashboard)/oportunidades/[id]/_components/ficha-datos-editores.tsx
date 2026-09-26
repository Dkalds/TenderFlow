"use client";

import * as React from "react";
import { Pencil } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { useUpdatePursuit, type Pursuit, type UpdatePursuitInput } from "@/hooks/use-pursuits";
import { ApiError } from "@/lib/api-client";
import { numeroDeTexto } from "@/lib/forms/valores";
import { formatCompactCurrency } from "@/lib/utils";

/**
 * Los editores de las celdas de la rejilla de datos (`ficha-datos.tsx`): la
 * oferta prevista y el responsable. Cada uno se lleva el foco al abrirse
 * —también se abren desde el paso pendiente, lejos de aquí, y enfocar trae la
 * celda a la vista— y guarda con la versión que se estaba viendo.
 */

const SIN_ASIGNAR = "sin-asignar";

function mensajeDeError(error: unknown, porDefecto: string): string {
  return error instanceof ApiError && error.status === 409
    ? "Alguien del equipo la cambió mientras la tenías abierta"
    : porDefecto;
}

/** Guarda un cambio de la rejilla con `expected_version`, como el resto de la ficha. */
function useGuardarDato(pursuit: Pursuit, onCerrar: () => void) {
  const actualizar = useUpdatePursuit(pursuit.id);
  const guardar = (cambios: UpdatePursuitInput, exito: string, fallo: string) =>
    actualizar.mutate(
      { ...cambios, expected_version: pursuit.version },
      {
        onSuccess: () => {
          onCerrar();
          toast.success(exito);
        },
        onError: (error) =>
          toast.error(mensajeDeError(error, fallo), {
            description: error instanceof Error ? error.message : undefined,
          }),
      },
    );
  return { guardar, guardando: actualizar.isPending };
}

export function EditorOferta({ pursuit, onCerrar }: { pursuit: Pursuit; onCerrar: () => void }) {
  const [texto, setTexto] = React.useState(pursuit.offer_price_eur?.toString() ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const { guardar, guardando } = useGuardarDato(pursuit, onCerrar);
  const entrada = React.useRef<HTMLInputElement>(null);
  const inputId = React.useId();
  const errorId = React.useId();

  React.useEffect(() => entrada.current?.focus(), []);

  const enviar = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const importe = numeroDeTexto(texto);
    // La misma regla que el formulario completo (`importeOpcional`): vacío
    // borra el dato; si hay algo, una cifra no negativa.
    if (texto.trim() && (importe == null || importe < 0)) {
      setError("Escribe un importe en euros: solo cifras, sin signo negativo.");
      return;
    }
    guardar(
      { offer_price_eur: importe },
      importe == null ? "Oferta prevista borrada" : `Oferta prevista: ${formatCompactCurrency(importe)}`,
      "No se pudo guardar la oferta prevista",
    );
  };

  return (
    <form onSubmit={enviar} noValidate className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="sr-only">
        Oferta prevista, en euros
      </label>
      <Input
        ref={entrada}
        id={inputId}
        inputMode="decimal"
        value={texto}
        onChange={(event) => {
          setTexto(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCerrar();
        }}
        placeholder="Ej. 170000"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className="h-8 font-mono"
      />
      {error ? (
        <p id={errorId} role="alert" className="text-destructive text-tf-micro leading-[1.35]">
          {error}
        </p>
      ) : null}
      <span className="flex flex-wrap gap-1">
        <Button type="submit" size="sm" disabled={guardando}>
          Guardar
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCerrar}>
          Cancelar
        </Button>
      </span>
    </form>
  );
}

export function EditorResponsable({ pursuit, onCerrar }: { pursuit: Pursuit; onCerrar: () => void }) {
  const miembros = useOrganizationMembers(pursuit.organization_id).data ?? [];
  const { guardar, guardando } = useGuardarDato(pursuit, onCerrar);
  const disparador = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => disparador.current?.focus(), []);

  const elegir = (valor: string) => {
    const id = valor === SIN_ASIGNAR ? null : Number(valor);
    if (id === (pursuit.responsible_user_id ?? null)) {
      onCerrar();
      return;
    }
    const nombre = miembros.find((miembro) => miembro.user_id === id);
    guardar(
      { responsible_user_id: id },
      id == null
        ? "Oportunidad sin responsable"
        : `Responsable: ${nombre?.display_name ?? nombre?.email ?? `Usuario ${id}`}`,
      "No se pudo cambiar el responsable",
    );
  };

  return (
    <div className="flex flex-col gap-1.5">
      <Select
        value={pursuit.responsible_user_id ? String(pursuit.responsible_user_id) : SIN_ASIGNAR}
        onValueChange={elegir}
        disabled={guardando}
      >
        <SelectTrigger ref={disparador} aria-label="Responsable de la oportunidad" className="h-8 text-tf-meta">
          <SelectValue placeholder="Elige a alguien" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={SIN_ASIGNAR}>Sin asignar</SelectItem>
          {miembros.map((miembro) => (
            <SelectItem key={miembro.user_id} value={String(miembro.user_id)}>
              {miembro.display_name ?? miembro.email ?? `Usuario ${miembro.user_id}`}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="button" variant="ghost" size="sm" className="self-start" onClick={onCerrar}>
        Cancelar
      </Button>
    </div>
  );
}

/** El lápiz de la celda: solo icono, con el nombre de lo que edita. */
export function BotonEditar({ etiqueta, onClick }: { etiqueta: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={etiqueta}
      onClick={onClick}
      // 24×24 de diana (WCAG 2.5.8) con margen negativo: el rótulo no se mueve.
      className="tf-pressable text-muted-foreground hover:text-foreground hover:bg-muted -my-1 -mr-1 grid size-6 flex-none place-items-center rounded-md transition-colors"
    >
      <Pencil className="h-3 w-3" aria-hidden="true" />
    </button>
  );
}
