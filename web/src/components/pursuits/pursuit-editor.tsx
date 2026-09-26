"use client";

import type * as React from "react";
import { Loader2, Save } from "lucide-react";
import { useForm, useWatch, type PathValue } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type * as z from "zod/mini";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { esTerminal, type Pursuit, type PursuitDecision, useUpdatePursuit } from "@/hooks/use-pursuits";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { decisionLabel, outcomeLabel } from "@/components/pursuits/pursuit-presenters";
import { MOTIVOS_PERDIDA, errorDeCierre, esMotivoPerdida, pideCodificar } from "@/lib/motivos-perdida";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { oportunidad } from "@/lib/forms/esquemas";
import { numeroDeTexto } from "@/lib/forms/valores";
import { cn } from "@/lib/utils";

/** Valores del formulario: claves de `PursuitUpdate`, del esquema de S7.2. */
type FormState = z.input<typeof oportunidad.esquema>;

const TODAS: readonly PursuitDecision[] = ["pending", "go", "no_go"];

function formFrom(pursuit: Pursuit): FormState {
  return {
    status: pursuit.status,
    responsible_user_id: pursuit.responsible_user_id?.toString() ?? "",
    decision: pursuit.decision,
    decision_reason: pursuit.decision_reason ?? "",
    offer_price_eur: pursuit.offer_price_eur?.toString() ?? "",
    outcome: pursuit.outcome,
    awarded_amount_eur: pursuit.awarded_amount_eur?.toString() ?? "",
    outcome_reason: pursuit.outcome_reason ?? "",
    outcome_reason_code: pursuit.outcome_reason_code ?? "",
  };
}

/**
 * «Editar todos los campos»: el formulario entero de la oportunidad.
 *
 * Es el sitio de las correcciones, no el del día a día —avanzar, decidir, la
 * oferta y la próxima acción tienen su control arriba—, así que solo ofrece lo
 * que el backend acepta en la fase en que está la oportunidad:
 *
 * - `decisiones` son las que el PATCH admite sin mover la fase (la ficha las
 *   saca de `_lib/flujo.ts`). Antes el desplegable ofrecía un NO-GO en
 *   «Identificada» que acababa en un 422.
 * - El cierre (resultado, importe adjudicado, motivo, nota) solo aparece con la
 *   oportunidad cerrada, para completarlo. Cerrar se hace con «Registrar
 *   resultado» o «Retirar…»: aquí elegir «Ganada» desde «Identificada» era otro
 *   422, y el resultado de una cerrada ya no cambia.
 * - «Guardar cambios» solo se activa, y solo se queda fijo al pie, cuando hay
 *   algo que guardar: fijo y naranja sin cambios competía con la acción de la
 *   fase.
 */
export function PursuitEditor({
  pursuit,
  decisiones = TODAS,
}: {
  pursuit: Pursuit;
  decisiones?: readonly PursuitDecision[];
}) {
  return <PursuitEditorForm key={`${pursuit.id}:${pursuit.version}`} pursuit={pursuit} decisiones={decisiones} />;
}

function PursuitEditorForm({
  pursuit,
  decisiones,
}: {
  pursuit: Pursuit;
  decisiones: readonly PursuitDecision[];
}) {
  const update = useUpdatePursuit(pursuit.id);
  const members = useOrganizationMembers(pursuit.organization_id).data ?? [];
  // react-hook-form + esquema de `PursuitUpdate` (S7.2): un importe ilegible
  // o negativo se explica bajo su campo en vez de viajar como `null`.
  const formulario = useForm<FormState>({ resolver: zodResolver(oportunidad.esquema), defaultValues: formFrom(pursuit) });
  const form = useWatch({ control: formulario.control }) as FormState;
  const errores = formulario.formState.errors;
  const sucio = formulario.formState.isDirty;
  // F3.1: la regla del motivo cruza campos, así que va aparte del esquema.
  const intentado = formulario.formState.isSubmitted;
  const errorMotivo = errorDeCierre(form.outcome, form.outcome_reason_code, form.outcome_reason);
  const cerrada = esTerminal(pursuit.status);
  // La que tiene siempre se enseña, aunque la regla ya no la admita: el
  // desplegable no puede mostrar vacío el dato guardado.
  const opcionesDecision = TODAS.filter((opcion) => decisiones.includes(opcion) || opcion === pursuit.decision);
  const decisionFija = decisiones.length === 1;

  const guardar = async (form: FormState) => {
    const error = errorDeCierre(form.outcome, form.outcome_reason_code, form.outcome_reason);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await update.mutateAsync({
        // Sin control propio: la fase se mueve desde «Para salir de…» y el
        // resultado de una cerrada ya no cambia. Viaja el valor que ya tenía,
        // y `expected_version` corta si alguien la movió.
        status: form.status,
        responsible_user_id: form.responsible_user_id.trim() ? Number(form.responsible_user_id) : null,
        decision: form.decision,
        decision_reason: form.decision_reason.trim() || null,
        offer_price_eur: numeroDeTexto(form.offer_price_eur),
        outcome: form.outcome,
        awarded_amount_eur: numeroDeTexto(form.awarded_amount_eur),
        outcome_reason: form.outcome_reason.trim() || null,
        // Sólo viaja al completar una pérdida: en cualquier otro resultado el
        // código no significa nada y no se toca.
        ...(form.outcome === "lost" && form.outcome_reason_code
          ? { outcome_reason_code: form.outcome_reason_code }
          : {}),
        expected_version: pursuit.version,
      });
      toast.success("Oportunidad actualizada");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo guardar la oportunidad");
    }
  };

  const save = (event: React.FormEvent<HTMLFormElement>) => formulario.handleSubmit(guardar)(event);
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    formulario.setValue(key, value as PathValue<FormState, K>, {
      shouldDirty: true,
      shouldValidate: formulario.formState.isSubmitted,
    });
  const inputId = (name: string) => `pursuit-${pursuit.id}-${name}`;
  const etiqueta = "block space-y-1.5 text-tf-meta font-medium";
  const ayuda = "block text-tf-micro font-normal text-muted-foreground";

  return (
    <form onSubmit={save} noValidate className="flex flex-col gap-5">
      <fieldset>
        <legend className="text-muted-foreground mb-1 font-mono text-tf-micro font-semibold tracking-wider uppercase">
          Decisión y responsable
        </legend>
        <p className={cn(ayuda, "mb-3")}>
          La fase se cambia desde «Para salir de…», arriba. Aquí se corrigen los datos de la
          oportunidad.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className={etiqueta} htmlFor={inputId("owner")}>
            Responsable
            <Select
              value={form.responsible_user_id || "unassigned"}
              onValueChange={(value) => set("responsible_user_id", value === "unassigned" ? "" : value)}
            >
              <SelectTrigger id={inputId("owner")}>
                <SelectValue placeholder="Sin asignar" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="unassigned">Sin asignar</SelectItem>
                {members.map((member) => (
                  <SelectItem key={member.user_id} value={String(member.user_id)}>
                    {member.display_name ?? member.email ?? `Usuario ${member.user_id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className={ayuda}>Asigna una persona de tu organización.</span>
          </label>
          <label className={etiqueta} htmlFor={inputId("decision")}>
            Decisión
            <Select
              value={form.decision}
              disabled={decisionFija}
              onValueChange={(value) => set("decision", value as PursuitDecision)}
            >
              <SelectTrigger id={inputId("decision")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {opcionesDecision.map((opcion) => (
                  <SelectItem key={opcion} value={opcion}>
                    {decisionLabel(opcion)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className={ayuda}>
              {decisionFija
                ? "Con la oferta en marcha la decisión es GO. Para abandonarla, retírala."
                : decisiones.includes("no_go")
                  ? "El GO y el NO-GO exigen motivo."
                  : "El NO-GO se toma en la fase «Decisión»."}
            </span>
          </label>
          <label className={cn(etiqueta, "sm:col-span-2")} htmlFor={inputId("decision-reason")}>
            Motivo de la decisión
            <Textarea
              id={inputId("decision-reason")}
              value={form.decision_reason}
              onChange={(event) => set("decision_reason", event.target.value)}
              placeholder="Qué evidencia sostiene la decisión"
              {...ariaCampo(inputId("decision-reason"), errores.decision_reason?.message)}
            />
            <CampoError enLabel campoId={inputId("decision-reason")} mensaje={errores.decision_reason?.message} />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-muted-foreground mb-3 font-mono text-tf-micro font-semibold tracking-wider uppercase">
          {cerrada ? "Oferta y cierre" : "Oferta"}
        </legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className={etiqueta} htmlFor={inputId("offer-price")}>
            Oferta prevista (€)
            <Input
              id={inputId("offer-price")}
              inputMode="decimal"
              value={form.offer_price_eur}
              onChange={(event) => set("offer_price_eur", event.target.value)}
              placeholder="Ej. 125000"
              {...ariaCampo(inputId("offer-price"), errores.offer_price_eur?.message)}
            />
            <CampoError enLabel campoId={inputId("offer-price")} mensaje={errores.offer_price_eur?.message} />
          </label>

          {cerrada ? (
            <div className={etiqueta}>
              <span>Resultado</span>
              <p className="text-tf-body font-semibold">{outcomeLabel(pursuit.outcome)}</p>
              <span className={ayuda}>Una oportunidad cerrada ya no cambia de resultado.</span>
            </div>
          ) : null}

          {cerrada && pursuit.outcome === "won" ? (
            <label className={etiqueta} htmlFor={inputId("awarded-price")}>
              Importe adjudicado (€)
              <Input
                id={inputId("awarded-price")}
                inputMode="decimal"
                value={form.awarded_amount_eur}
                onChange={(event) => set("awarded_amount_eur", event.target.value)}
                placeholder="Solo si se conoce"
                {...ariaCampo(inputId("awarded-price"), errores.awarded_amount_eur?.message)}
              />
              <CampoError enLabel campoId={inputId("awarded-price")} mensaje={errores.awarded_amount_eur?.message} />
            </label>
          ) : null}

          {cerrada && form.outcome === "lost" ? (
            <div className={cn(etiqueta, "sm:col-span-2")}>
              {pideCodificar(pursuit) && !form.outcome_reason_code ? (
                <p
                  role="status"
                  className="border-border/70 bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-tf-micro font-normal"
                >
                  Este cierre es anterior a los motivos codificados y cuenta como «sin codificar» en el
                  reparto de pérdidas. Elige el motivo para completarlo.
                </p>
              ) : null}
              <label htmlFor={inputId("outcome-reason-code")}>Motivo de la pérdida</label>
              <Select
                value={form.outcome_reason_code}
                onValueChange={(value) => set("outcome_reason_code", esMotivoPerdida(value) ? value : "")}
              >
                <SelectTrigger
                  id={inputId("outcome-reason-code")}
                  aria-required="true"
                  aria-invalid={intentado && Boolean(errorMotivo)}
                  aria-describedby={inputId("outcome-reason-code-ayuda")}
                >
                  <SelectValue placeholder="Elige un motivo" />
                </SelectTrigger>
                <SelectContent>
                  {MOTIVOS_PERDIDA.map((motivo) => (
                    <SelectItem key={motivo.codigo} value={motivo.codigo}>
                      {motivo.etiqueta}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span id={inputId("outcome-reason-code-ayuda")} className={ayuda}>
                {MOTIVOS_PERDIDA.find((motivo) => motivo.codigo === form.outcome_reason_code)?.ayuda ??
                  "Obligatorio al cerrar como perdida: es lo que permite saber por qué se pierde."}
              </span>
              {intentado && errorMotivo ? (
                <span role="alert" className="text-destructive block text-tf-micro font-normal">
                  {errorMotivo}
                </span>
              ) : null}
            </div>
          ) : null}

          {cerrada ? (
            <label className={cn(etiqueta, "sm:col-span-2")} htmlFor={inputId("outcome-reason")}>
              {form.outcome === "lost" && form.outcome_reason_code === "otro"
                ? "Nota de cierre (obligatoria con «Otro»)"
                : "Nota de cierre"}
              <Textarea
                id={inputId("outcome-reason")}
                value={form.outcome_reason}
                onChange={(event) => set("outcome_reason", event.target.value)}
                placeholder="Contexto del resultado o ausencia de importe"
                {...ariaCampo(inputId("outcome-reason"), errores.outcome_reason?.message)}
              />
              <CampoError enLabel campoId={inputId("outcome-reason")} mensaje={errores.outcome_reason?.message} />
            </label>
          ) : null}
        </div>
      </fieldset>

      <div className={cn("flex items-center justify-end gap-3", sucio && "sticky bottom-4 z-10")}>
        {!sucio ? <p className="text-muted-foreground text-tf-micro">Sin cambios que guardar.</p> : null}
        <Button type="submit" disabled={!sucio || update.isPending}>
          {update.isPending ? <Loader2 className="animate-spin" /> : <Save />}Guardar cambios
        </Button>
      </div>
    </form>
  );
}
