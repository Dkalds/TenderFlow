"use client";

/**
 * Las dos entradas de la dimensión «afinidad»: keywords libres y códigos CPV.
 *
 * Van juntas porque son la misma decisión partida en dos vocabularios —qué
 * texto y qué clasificación te interesan— y comparten el mismo gesto de añadir
 * con Enter y quitar pulsando el chip.
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { isValidCpv } from "../_hooks/use-perfil-scoring";

export function KeywordsAfinidadCard({
  keywords,
  kwInput,
  onKwInputChange,
  onAdd,
  onRemove,
}: {
  keywords: string[];
  kwInput: string;
  onKwInputChange: (value: string) => void;
  onAdd: () => void;
  onRemove: (kw: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Keywords de afinidad</CardTitle>
        <CardDescription>
          Las licitaciones cuyo título o descripción contengan estas palabras reciben puntos
          extra en la dimensión &quot;Afinidad&quot;. Se busca la palabra completa. Sin
          keywords ni CPVs, esa dimensión se omite y su peso se redistribuye.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            placeholder="p.ej. consultoría, mantenimiento, SAP…"
            value={kwInput}
            onChange={(e) => onKwInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onAdd();
              }
            }}
            className="flex-1"
          />
          <Button variant="outline" onClick={onAdd} disabled={!kwInput.trim()}>
            Añadir
          </Button>
        </div>
        {keywords.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {keywords.map((kw) => (
              <Badge
                key={kw}
                variant="secondary"
                className="cursor-pointer gap-1 pr-1.5 hover:bg-destructive/10"
                onClick={() => onRemove(kw)}
              >
                {kw}
                <span className="ml-0.5 text-muted-foreground">×</span>
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Sin keywords configuradas — afinidad desactivada (scoring global).
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function CpvsInteresCard({
  cpvs,
  cpvInput,
  onCpvInputChange,
  onAdd,
  onRemove,
}: {
  cpvs: string[];
  cpvInput: string;
  onCpvInputChange: (value: string) => void;
  onAdd: () => void;
  onRemove: (cpv: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>CPVs de interés</CardTitle>
        <CardDescription>
          Códigos CPV en los que trabajáis. Una licitación con el mismo código puntúa afinidad
          máxima; si comparte los 4 primeros dígitos (la misma división), un 80%. Acepta de 4 a
          8 dígitos.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            placeholder="p.ej. 72000000, 4823…"
            value={cpvInput}
            inputMode="numeric"
            onChange={(e) => onCpvInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onAdd();
              }
            }}
            className="flex-1"
          />
          <Button variant="outline" onClick={onAdd} disabled={!isValidCpv(cpvInput)}>
            Añadir
          </Button>
        </div>
        {cpvInput.trim() !== "" && !isValidCpv(cpvInput) && (
          <p className="text-xs text-destructive">
            Un CPV son entre 4 y 8 dígitos, sin letras ni guiones.
          </p>
        )}
        {cpvs.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {cpvs.map((cpv) => (
              <Badge
                key={cpv}
                variant="secondary"
                className="cursor-pointer gap-1 pr-1.5 font-mono hover:bg-destructive/10"
                onClick={() => onRemove(cpv)}
              >
                {cpv}
                <span className="ml-0.5 text-muted-foreground">×</span>
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Sin CPVs configurados — la afinidad solo mira tus keywords.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
