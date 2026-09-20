"use client";

import type * as React from "react";
import { Check, CircleDollarSign, Loader2, Save } from "lucide-react";
import { useForm, useWatch, type PathValue } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type * as z from "zod/mini";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { type Pursuit, type PursuitDecision, type PursuitOutcome, useUpdatePursuit } from "@/hooks/use-pursuits";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { PursuitDecisionBadge, PursuitOutcomeBadge } from "@/components/pursuits/pursuit-presenters";
import { MOTIVOS_PERDIDA, errorDeCierre, esMotivoPerdida, pideCodificar } from "@/lib/motivos-perdida";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { oportunidad } from "@/lib/forms/esquemas";
import { numeroDeTexto } from "@/lib/forms/valores";

/** Valores del formulario: claves de `PursuitUpdate`, del esquema de S7.2. */
type FormState = z.input<typeof oportunidad.esquema>;

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


/** The operational form keeps the canonical business dimensions visibly separate. */
export function PursuitEditor({ pursuit }: { pursuit: Pursuit }) {
  return <PursuitEditorForm key={`${pursuit.id}:${pursuit.version}`} pursuit={pursuit} />;
}

function PursuitEditorForm({ pursuit }: { pursuit: Pursuit }) {
  const update = useUpdatePursuit(pursuit.id);
  const members = useOrganizationMembers(pursuit.organization_id).data ?? [];
  // react-hook-form + esquema de `PursuitUpdate` (S7.2): un importe ilegible
  // o negativo se explica bajo su campo en vez de viajar como `null`.
  const formulario = useForm<FormState>({ resolver: zodResolver(oportunidad.esquema), defaultValues: formFrom(pursuit) });
  const form = useWatch({ control: formulario.control }) as FormState;
  const errores = formulario.formState.errors;
  // F3.1: la regla del motivo cruza campos, así que va aparte del esquema.
  const intentado = formulario.formState.isSubmitted;
  const errorMotivo = errorDeCierre(form.outcome, form.outcome_reason_code, form.outcome_reason);

  const guardar = async (form: FormState) => {
    const error = errorDeCierre(form.outcome, form.outcome_reason_code, form.outcome_reason);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await update.mutateAsync({
        // Sin control propio desde que la fase vive en el path de la ficha:
        // viaja el valor que ya tenía, y `expected_version` corta si alguien la
        // movió. Elegir un resultado sí la fija, porque el backend deriva el
        // estado terminal del `outcome`.
        status: form.status,
        responsible_user_id: form.responsible_user_id.trim() ? Number(form.responsible_user_id) : null,
        decision: form.decision,
        decision_reason: form.decision_reason.trim() || null,
        offer_price_eur: numeroDeTexto(form.offer_price_eur),
        outcome: form.outcome,
        awarded_amount_eur: numeroDeTexto(form.awarded_amount_eur),
        outcome_reason: form.outcome_reason.trim() || null,
        // Sólo viaja al cerrar (o completar) una pérdida: en cualquier otro
        // resultado el código no significa nada y no se toca.
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

  return (
    <form onSubmit={save} noValidate className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <div><CardTitle className="flex items-center gap-2"><Check className="h-4 w-4 text-primary" />Decisión y responsable</CardTitle><p className="mt-1 text-sm text-muted-foreground">La fase se cambia en el path de la cabecera; esto es la decisión de negocio.</p></div>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("owner")}>Responsable
            <Select
              value={form.responsible_user_id || "unassigned"}
              onValueChange={(value) => set("responsible_user_id", value === "unassigned" ? "" : value)}
            >
              <SelectTrigger id={inputId("owner")}><SelectValue placeholder="Sin asignar" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="unassigned">Sin asignar</SelectItem>
                {members.map((member) => (
                  <SelectItem key={member.user_id} value={String(member.user_id)}>
                    {member.display_name ?? member.email ?? `Usuario ${member.user_id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="block text-xs font-normal text-muted-foreground">Asigna una persona de tu organización.</span>
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("decision")}>Decisión
            <Select value={form.decision} onValueChange={(value) => set("decision", value as PursuitDecision)}><SelectTrigger id={inputId("decision")}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pending">Pendiente</SelectItem><SelectItem value="go">GO</SelectItem><SelectItem value="no_go">NO-GO</SelectItem></SelectContent></Select>
            <PursuitDecisionBadge decision={form.decision} />
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("decision-reason")}>Motivo
            <Textarea id={inputId("decision-reason")} value={form.decision_reason} onChange={(event) => set("decision_reason", event.target.value)} placeholder="Qué evidencia sostiene la decisión" {...ariaCampo(inputId("decision-reason"), errores.decision_reason?.message)} />
            <CampoError enLabel campoId={inputId("decision-reason")} mensaje={errores.decision_reason?.message} />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0"><div><CardTitle className="flex items-center gap-2"><CircleDollarSign className="h-4 w-4 text-primary" />Oferta y resultado</CardTitle><p className="mt-1 text-sm text-muted-foreground">Separamos importe ofertado, resultado y adjudicación.</p></div><PursuitOutcomeBadge outcome={form.outcome} /></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("offer-price")}>Precio ofertado (€)
            <Input id={inputId("offer-price")} inputMode="decimal" value={form.offer_price_eur} onChange={(event) => set("offer_price_eur", event.target.value)} placeholder="Ej. 125000" {...ariaCampo(inputId("offer-price"), errores.offer_price_eur?.message)} />
            <CampoError enLabel campoId={inputId("offer-price")} mensaje={errores.offer_price_eur?.message} />
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("outcome")}>Resultado
            <Select value={form.outcome} onValueChange={(value) => {
              const outcome = value as PursuitOutcome;
              set("outcome", outcome);
              if (outcome === "won" || outcome === "lost") set("status", outcome);
              if (outcome === "cancelled") set("status", "withdrawn");
            }}><SelectTrigger id={inputId("outcome")}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pending">Sin cerrar</SelectItem><SelectItem value="won">Ganada</SelectItem><SelectItem value="lost">Perdida</SelectItem><SelectItem value="cancelled">Cancelada</SelectItem></SelectContent></Select>
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("awarded-price")}>Importe adjudicado (€)
            <Input id={inputId("awarded-price")} inputMode="decimal" value={form.awarded_amount_eur} onChange={(event) => set("awarded_amount_eur", event.target.value)} placeholder="Solo si se conoce" {...ariaCampo(inputId("awarded-price"), errores.awarded_amount_eur?.message)} />
            <CampoError enLabel campoId={inputId("awarded-price")} mensaje={errores.awarded_amount_eur?.message} />
          </label>
          {form.outcome === "lost" && (
            <div className="space-y-1.5 text-sm font-medium sm:col-span-2">
              {pideCodificar(pursuit) && !form.outcome_reason_code ? (
                <p role="status" className="rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-xs font-normal text-muted-foreground">
                  Este cierre es anterior a los motivos codificados y cuenta como «sin codificar» en el reparto de pérdidas. Elige el motivo para completarlo.
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
                    <SelectItem key={motivo.codigo} value={motivo.codigo}>{motivo.etiqueta}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span id={inputId("outcome-reason-code-ayuda")} className="block text-xs font-normal text-muted-foreground">
                {MOTIVOS_PERDIDA.find((motivo) => motivo.codigo === form.outcome_reason_code)?.ayuda ??
                  "Obligatorio al cerrar como perdida: es lo que permite saber por qué se pierde."}
              </span>
              {intentado && errorMotivo ? (
                <span role="alert" className="block text-xs font-normal text-destructive">{errorMotivo}</span>
              ) : null}
            </div>
          )}
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("outcome-reason")}>
            {form.outcome === "lost" && form.outcome_reason_code === "otro" ? "Nota de cierre (obligatoria con «Otro»)" : "Nota de cierre"}
            <Textarea id={inputId("outcome-reason")} value={form.outcome_reason} onChange={(event) => set("outcome_reason", event.target.value)} placeholder="Contexto del resultado o ausencia de importe" {...ariaCampo(inputId("outcome-reason"), errores.outcome_reason?.message)} />
            <CampoError enLabel campoId={inputId("outcome-reason")} mensaje={errores.outcome_reason?.message} />
          </label>
        </CardContent>
      </Card>
      <div className="sticky bottom-4 z-10 flex justify-end"><Button type="submit" disabled={update.isPending}>{update.isPending ? <Loader2 className="animate-spin" /> : <Save />}Guardar cambios</Button></div>
    </form>
  );
}
