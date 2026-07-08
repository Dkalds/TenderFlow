"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Trash2, RotateCcw, Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { toast } from "sonner";
import { fetchWithAuth, apiMutate } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------

interface UserProfile {
  weights?: Record<string, number> | null;
  afinidad_keywords?: string[] | null;
  importe_min?: number | null;
  importe_max?: number | null;
  updated_at?: string | null;
}

const DEFAULT_WEIGHTS: Record<string, number> = {
  importe: 25,
  plazo: 15,
  competencia: 25,
  margen: 20,
  afinidad: 15,
};

const WEIGHT_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad (keywords)",
};

const WEIGHT_DESCRIPTIONS: Record<string, string> = {
  importe: "Puntúa según la posición del contrato en el rango P10-P90 del mercado.",
  plazo: "Premia los contratos con plazo de presentación próximo (7-90 días).",
  competencia: "Favorece segmentos CPV con menos licitadores históricos.",
  margen: "Favorece contratos con baja esperada menor (más margen).",
  afinidad: "Puntúa matches con tus keywords de interés. Se omite si no hay keywords.",
};

const PROFILE_KEY = ["me", "profile"] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sumWeights(w: Record<string, number>): number {
  return Object.values(w).reduce((a, b) => a + b, 0);
}

function formatCurrency(v: number) {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(v);
}

// ---------------------------------------------------------------------------
// Componente de slider de peso
// ---------------------------------------------------------------------------

function WeightSlider({
  name,
  value,
  onChange,
  disabled,
}: {
  name: string;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">{WEIGHT_LABELS[name] ?? name}</p>
          <p className="text-xs text-muted-foreground">{WEIGHT_DESCRIPTIONS[name]}</p>
        </div>
        <span className="ml-4 w-10 shrink-0 rounded bg-muted px-2 py-0.5 text-center text-sm font-semibold tabular-nums">
          {value}
        </span>
      </div>
      <Slider
        min={0}
        max={100}
        step={1}
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        disabled={disabled}
        className="w-full"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Página principal
// ---------------------------------------------------------------------------

export default function MiPerfilPage() {
  const queryClient = useQueryClient();

  // Carga del perfil actual
  const { data, isLoading } = useQuery<UserProfile>({
    queryKey: PROFILE_KEY,
    queryFn: () => fetchWithAuth<UserProfile>("/api/v1/me/profile"),
    staleTime: 60_000,
  });

  // Estado local del formulario
  const [weights, setWeights] = useState<Record<string, number>>(DEFAULT_WEIGHTS);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [kwInput, setKwInput] = useState("");
  const [importeMin, setImporteMin] = useState("");
  const [importeMax, setImporteMax] = useState("");
  const [dirty, setDirty] = useState(false);

  // Rellenar formulario cuando llegan datos del servidor
  useEffect(() => {
    if (!data) return;
    setWeights(data.weights ?? DEFAULT_WEIGHTS); // eslint-disable-line react-hooks/set-state-in-effect
    setKeywords(data.afinidad_keywords ?? []);
    setImporteMin(data.importe_min != null ? String(data.importe_min) : "");
    setImporteMax(data.importe_max != null ? String(data.importe_max) : "");
    setDirty(false);
  }, [data]);

  // Validación de suma de pesos
  const total = sumWeights(weights);
  const weightsValid = total === 100;

  // Mutación guardar
  const saveMut = useMutation({
    mutationFn: () =>
      apiMutate<UserProfile>("PUT", "/api/v1/me/profile", {
        weights: weightsValid ? weights : null,
        afinidad_keywords: keywords.length > 0 ? keywords : null,
        importe_min: importeMin !== "" ? Number(importeMin) : null,
        importe_max: importeMax !== "" ? Number(importeMax) : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      setDirty(false);
      toast.success("Perfil guardado. El scoring usará tus pesos personalizados.");
    },
    onError: () => toast.error("No se pudo guardar el perfil."),
  });

  // Mutación eliminar
  const deleteMut = useMutation({
    mutationFn: () => apiMutate("DELETE", "/api/v1/me/profile"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      setWeights(DEFAULT_WEIGHTS);
      setKeywords([]);
      setImporteMin("");
      setImporteMax("");
      setDirty(false);
      toast.success("Perfil eliminado. El scoring vuelve a los valores globales.");
    },
    onError: () => toast.error("No se pudo eliminar el perfil."),
  });

  function handleWeightChange(name: string, value: number) {
    setWeights((prev) => ({ ...prev, [name]: value }));
    setDirty(true);
  }

  function handleResetWeights() {
    setWeights(DEFAULT_WEIGHTS);
    setDirty(true);
  }

  function addKeyword() {
    const kw = kwInput.trim().toLowerCase();
    if (!kw || keywords.includes(kw)) return;
    setKeywords((prev) => [...prev, kw]);
    setKwInput("");
    setDirty(true);
  }

  function removeKeyword(kw: string) {
    setKeywords((prev) => prev.filter((k) => k !== kw));
    setDirty(true);
  }

  const hasProfile = data && (data.weights != null || data.afinidad_keywords != null || data.importe_min != null || data.importe_max != null);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Mi perfil de scoring</h1>
        <p className="text-muted-foreground mt-1">
          Personaliza cómo se puntúan las oportunidades. Los cambios aplican en el panel de
          detalle y en el ranking de la vista de Tecnologías.
        </p>
        {hasProfile && (
          <p className="mt-2 text-xs text-muted-foreground">
            Última actualización:{" "}
            {data.updated_at ? new Date(data.updated_at).toLocaleString("es-ES") : "—"}
          </p>
        )}
      </div>

      {/* Pesos de scoring */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Pesos de scoring</CardTitle>
              <CardDescription>Los 5 pesos deben sumar exactamente 100.</CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={handleResetWeights} className="gap-1.5">
              <RotateCcw className="h-3.5 w-3.5" />
              Resetear
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {Object.entries(weights).map(([name, value]) => (
            <WeightSlider
              key={name}
              name={name}
              value={value}
              onChange={(v) => handleWeightChange(name, v)}
            />
          ))}

          {/* Indicador de suma */}
          <div
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
              weightsValid
                ? "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-300"
                : "border-destructive/40 bg-destructive/5 text-destructive"
            }`}
          >
            <Info className="h-4 w-4 shrink-0" />
            <span>
              Suma actual: <strong>{total}</strong> / 100
              {!weightsValid && " — ajusta los sliders hasta llegar a 100"}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Keywords de afinidad */}
      <Card>
        <CardHeader>
          <CardTitle>Keywords de afinidad</CardTitle>
          <CardDescription>
            Las licitaciones cuyo título contenga estas palabras reciben puntos extra en la
            dimensión &quot;Afinidad&quot;. Sin keywords, esa dimensión se omite y su peso se
            redistribuye.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              placeholder="p.ej. consultoría, mantenimiento, SAP…"
              value={kwInput}
              onChange={(e) => setKwInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addKeyword();
                }
              }}
              className="flex-1"
            />
            <Button variant="outline" onClick={addKeyword} disabled={!kwInput.trim()}>
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
                  onClick={() => removeKeyword(kw)}
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

      {/* Rango de importe */}
      <Card>
        <CardHeader>
          <CardTitle>Rango de importe ejecutable</CardTitle>
          <CardDescription>
            Los contratos fuera de este rango reciben una penalización de −15 puntos
            (flag <code>fuera_de_rango</code>). Deja en blanco para no aplicar restricción.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label htmlFor="mp-importe-min" className="text-sm font-medium">
                Mínimo (€)
              </label>
              <Input
                id="mp-importe-min"
                type="number"
                min={0}
                placeholder="Sin mínimo"
                value={importeMin}
                onChange={(e) => {
                  setImporteMin(e.target.value);
                  setDirty(true);
                }}
              />
              {importeMin !== "" && !isNaN(Number(importeMin)) && (
                <p className="text-xs text-muted-foreground">{formatCurrency(Number(importeMin))}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="mp-importe-max" className="text-sm font-medium">
                Máximo (€)
              </label>
              <Input
                id="mp-importe-max"
                type="number"
                min={0}
                placeholder="Sin máximo"
                value={importeMax}
                onChange={(e) => {
                  setImporteMax(e.target.value);
                  setDirty(true);
                }}
              />
              {importeMax !== "" && !isNaN(Number(importeMax)) && (
                <p className="text-xs text-muted-foreground">{formatCurrency(Number(importeMax))}</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Acciones */}
      <div className="flex items-center gap-3 pb-6">
        <Button
          onClick={() => saveMut.mutate()}
          disabled={!dirty || !weightsValid || saveMut.isPending}
          className="gap-1.5"
        >
          <Save className="h-4 w-4" />
          {saveMut.isPending ? "Guardando…" : "Guardar perfil"}
        </Button>
        {hasProfile && (
          <Button
            variant="outline"
            onClick={() => deleteMut.mutate()}
            disabled={deleteMut.isPending}
            className="gap-1.5 text-destructive hover:bg-destructive/10"
          >
            <Trash2 className="h-4 w-4" />
            {deleteMut.isPending ? "Eliminando…" : "Eliminar perfil"}
          </Button>
        )}
        {dirty && !weightsValid && (
          <p className="text-sm text-destructive">Los pesos deben sumar 100 para guardar.</p>
        )}
      </div>
    </div>
  );
}
