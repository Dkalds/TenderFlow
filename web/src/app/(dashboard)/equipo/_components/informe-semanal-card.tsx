"use client";

/**
 * Cuándo sale el informe semanal de la organización (T6).
 *
 * Existe por una razón concreta: el backend de T6 nace **apagado** para todas
 * las organizaciones, a propósito (ver `docs/informes-programados.md`). Sin
 * esta tarjeta el único modo de encenderlo sería un `PUT` a mano, es decir,
 * nadie lo encendería — «infraestructura sin consumidor».
 *
 * Vive junto a `TecnologiasOrganizacionCard`, en Equipo › Organización, porque
 * es lo mismo: un ajuste de organización, no del usuario, editable sólo por
 * propietarios y administradores. Estuvo en Mi perfil, entre los pesos de
 * cada uno, con su propio botón de guardar.
 *
 * El día y la hora se eligen en el horario de quien configura y se guardan en
 * UTC; la conversión y sus límites están en `_lib/horario-informe.ts`.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { type OrganizacionActiva } from "@/hooks/use-organization";
import { DIAS, useGuardarReportSchedule, useReportSchedule } from "@/hooks/use-report-schedule";
import { getErrorMessage } from "@/lib/query-feedback";
import { formatDateTime, formatDiaYHora } from "@/lib/utils";
import {
  aHorarioLocal,
  aHorarioUtc,
  horarioLocalDisponible,
  proximaEntrega,
} from "../_lib/horario-informe";

export { proximaEntrega };

/** Tope de la lista explícita. Espejo de `ReportSchedule.destinatarios` (DTO). */
const MAX_DESTINATARIOS = 25;

const HORAS = Array.from({ length: 24 }, (_, h) => h);

/**
 * Traduce `ultimo_estado` a algo que se pueda leer sin abrir los logs. Los
 * códigos los escribe `scheduler/jobs/informes_programados.py`.
 */
function explicarEstado(estado: string): string {
  if (estado.startsWith("enviado:")) {
    const [salieron, total] = estado.slice("enviado:".length).split("/");
    return salieron === total
      ? `Enviado a ${total} ${total === "1" ? "destinatario" : "destinatarios"}`
      : `Enviado a ${salieron} de ${total}; los demás correos se rechazaron`;
  }
  if (estado === "vacio") return "No se envió: esa semana no había nada que contar";
  if (estado === "sin_destinatarios") return "No se envió: no había ningún destinatario con correo";
  if (estado === "fallido") return "No salió ninguno: falló el proveedor de correo";
  return estado;
}

/** Separa por líneas o comas y quita lo vacío. */
function parsearDestinatarios(texto: string): string[] {
  return texto
    .split(/[\n,;]+/)
    .map((c) => c.trim())
    .filter(Boolean);
}

export function InformeSemanalCard({
  organizationId: organizacionActiva,
  canManage: puedeEditar,
}: {
  organizationId: OrganizacionActiva;
  canManage: boolean;
}) {
  // Sólo Dirección puede leer esto (el backend responde 403 al resto): se pasa
  // `null` para no gastar una petición que se sabe rechazada.
  const organizationId = puedeEditar ? organizacionActiva : null;
  const { data, isLoading, error, refetch } = useReportSchedule(organizationId);
  const guardar = useGuardarReportSchedule(organizationId);

  const [activo, setActivo] = useState(false);
  const [diaSemana, setDiaSemana] = useState(0);
  const [horaUtc, setHoraUtc] = useState(7);
  const [destinatarios, setDestinatarios] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    setActivo(data.activo);
    setDiaSemana(data.dia_semana);
    setHoraUtc(data.hora_utc);
    setDestinatarios((data.destinatarios ?? []).join("\n"));
    setDirty(false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [data]);

  if (!puedeEditar) return null;

  const lista = parsearDestinatarios(destinatarios);
  const proxima = proximaEntrega(diaSemana, horaUtc);
  // Lo que enseñan los dos selectores: la programación en el horario del
  // navegador, o en UTC donde la hora local no cae en una hora UTC entera.
  const enLocal = horarioLocalDisponible();
  const elegido = enLocal ? aHorarioLocal(diaSemana, horaUtc) : { dia: diaSemana, hora: horaUtc };
  const programar = (dia: number, hora: number) => {
    const utc = enLocal ? aHorarioUtc(dia, hora) : { dia_semana: dia, hora_utc: hora };
    setDiaSemana(utc.dia_semana);
    setHoraUtc(utc.hora_utc);
    setDirty(true);
  };

  const enviar = () => {
    // El validador de verdad es el `EmailStr` del DTO; esto sólo existe para
    // poder decir *qué* línea está mal en vez de devolver un 422 opaco.
    const sospechosa = lista.find((c) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c));
    if (sospechosa) {
      toast.error(`«${sospechosa}» no parece un correo.`);
      return;
    }
    if (lista.length > MAX_DESTINATARIOS) {
      toast.error(`Como mucho ${MAX_DESTINATARIOS} destinatarios; hay ${lista.length}.`);
      return;
    }
    guardar
      .mutateAsync({
        activo,
        dia_semana: diaSemana,
        hora_utc: horaUtc,
        destinatarios: lista.length > 0 ? lista : null,
      })
      .then(() => {
        setDirty(false);
        toast.success(
          activo
            ? `Informe programado. Próximo envío: ${formatDiaYHora(proxima)}.`
            : "Informe semanal desactivado.",
        );
      })
      .catch((error: unknown) => toast.error(getErrorMessage(error, "accion")));
  };

  return (
    <Panel>
      <PanelTitle title="Informe semanal por correo" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        El resumen semanal de Dirección (embudo abierto, plazos a catorce días, ganadas y perdidas) por correo, con
        el mismo contenido en PDF. Está desactivado hasta que lo actives.
      </p>
      <div className="space-y-4">
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : error ? (
          // Sin la programación leída, el formulario enseñaría «No se envía» y
          // los valores por defecto como si fueran los guardados.
          <PanelError
            variant="inline"
            title="No se pudo leer la programación del informe"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : (
          <>
            <label className="flex items-center gap-3 text-tf-body">
              <Switch
                checked={activo}
                onCheckedChange={(valor) => {
                  setActivo(valor);
                  setDirty(true);
                }}
                aria-label="Enviar el informe semanal"
              />
              {activo ? "Se envía cada semana" : "No se envía"}
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Día" htmlFor="informe-dia">
                <Select
                  value={String(elegido.dia)}
                  onValueChange={(valor) => programar(Number(valor), elegido.hora)}
                >
                  <SelectTrigger id="informe-dia" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DIAS.map((nombre, indice) => (
                      <SelectItem key={nombre} value={String(indice)}>
                        {nombre}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field label={enLocal ? "Hora" : "Hora (UTC)"} htmlFor="informe-hora">
                <Select
                  value={String(elegido.hora)}
                  onValueChange={(valor) => programar(elegido.dia, Number(valor))}
                >
                  <SelectTrigger id="informe-hora" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HORAS.map((h) => (
                      <SelectItem key={h} value={String(h)}>
                        {String(h).padStart(2, "0")}:00
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>

            {/* La pipeline corre cada cuatro horas: la hora programada es el
                momento a partir del cual sale, no el minuto exacto. Decirlo
                aquí evita el parte de incidencias de las 07:05. */}
            <p className="text-tf-meta text-muted-foreground">
              {enLocal ? "Próximo envío" : "En tu horario"}:{" "}
              <strong className="font-medium text-foreground">{formatDiaYHora(proxima)}</strong>. Se envía a partir
              de esa hora y puede tardar hasta cuatro horas.
              {enLocal && " Con el cambio de hora de marzo y octubre se desplaza una hora."}
            </p>

            <Field
              label="Destinatarios"
              htmlFor="informe-destinatarios"
              hint="Uno por línea. Déjalo vacío para que llegue a los propietarios y administradores que haya en cada envío. Si escribes direcciones, solo se envía a esas, aunque no sean cuentas de TenderFlow."
            >
              <Textarea
                id="informe-destinatarios"
                rows={3}
                value={destinatarios}
                placeholder="Vacío = todos los propietarios y administradores de la organización"
                onChange={(e) => {
                  setDestinatarios(e.target.value);
                  setDirty(true);
                }}
              />
            </Field>

            {data?.ultimo_envio_at && (
              <p className="text-tf-meta text-muted-foreground">
                Último envío: {formatDateTime(data.ultimo_envio_at)}
                {data.ultimo_estado ? ` · ${explicarEstado(data.ultimo_estado)}` : ""}
              </p>
            )}

            <Button size="sm" disabled={!dirty || guardar.isPending} onClick={enviar}>
              {guardar.isPending ? "Guardando…" : "Guardar programación"}
            </Button>
          </>
        )}
      </div>
    </Panel>
  );
}
