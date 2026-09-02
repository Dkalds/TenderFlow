"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Trash2, RotateCcw, Info, Download, ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import { fetchWithAuth, apiMutate } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import { SpaceShell } from "@/components/layout/space-shell";
import { formatDateTime } from "@/lib/utils";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import {
  useOrganizationSettings,
  useUpdateOrganizationSettings,
} from "@/hooks/use-organization-settings";
import { Checkbox } from "@/components/ui/checkbox";

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------

interface UserProfile {
  user_key?: string | null;
  weights?: Record<string, number> | null;
  afinidad_keywords?: string[] | null;
  cpvs?: string[] | null;
  importe_min?: number | null;
  importe_max?: number | null;
  updated_at?: string | null;
  organization_id?: number | null;
  visibility?: "private" | "organization";
  inherited?: boolean;
}

/** Mismo criterio que valida el backend: división, grupo o código completo. */
function isValidCpv(value: string): boolean {
  return /^\d{4,8}$/.test(value.trim());
}

// Debe reflejar `settings.SCORING_WEIGHTS`: es el reparto que el backend
// aplica a quien no tiene perfil, y el que se ofrece al crear uno.
const DEFAULT_WEIGHTS: Record<string, number> = {
  importe: 20,
  plazo: 15,
  competencia: 20,
  margen: 20,
  afinidad: 15,
  senal_tecnica: 10,
};

const WEIGHT_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad (keywords)",
  senal_tecnica: "Señal técnica",
};

const WEIGHT_DESCRIPTIONS: Record<string, string> = {
  importe: "Puntúa según la posición del contrato en el rango P10-P90 del mercado abierto.",
  plazo: "Premia los contratos con plazo de presentación próximo (7-90 días).",
  competencia: "Favorece segmentos CPV con menos licitadores históricos.",
  margen: "Favorece contratos con baja esperada menor (más margen).",
  afinidad: "Puntúa matches con tus keywords de interés. Se omite si no hay keywords.",
  senal_tecnica:
    "Premia la evidencia de tecnología en el pliego y el clasificador, de la tecnología que estés filtrando.",
};

const PROFILE_KEY = ["me", "profile"] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sumWeights(w: Record<string, number>): number {
  return Object.values(w).reduce((a, b) => a + b, 0);
}

/**
 * Pesos guardados → formulario, completando las dimensiones que falten con 0.
 *
 * Un perfil creado antes de que existiera una dimensión no la trae. Sin este
 * relleno, su slider no aparecería y el usuario no podría activarla nunca; con
 * el 0 explícito la ve, sabe que no está puntuando, y la suma sigue en 100.
 */
function hydrateWeights(saved: Record<string, number> | null | undefined): Record<string, number> {
  if (!saved) return DEFAULT_WEIGHTS;
  const ceros = Object.fromEntries(Object.keys(DEFAULT_WEIGHTS).map((k) => [k, 0]));
  return { ...ceros, ...saved };
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
// RGPD — exportar / eliminar mis datos (F13·C3.3b, plan Pliegos+RAG)
// ---------------------------------------------------------------------------

function GdprSection() {
  const [confirmDelete, setConfirmDelete] = useState(false);

  const exportMut = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/v1/me/data", { credentials: "include" });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.blob();
    },
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mis-datos-${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Descarga iniciada.");
    },
    onError: () => toast.error("No se pudo exportar tus datos."),
  });

  const deleteMut = useMutation({
    mutationFn: () => apiMutate("DELETE", "/api/v1/me"),
    onSuccess: () => {
      toast.success("Datos eliminados. Cerrando sesión…");
      setTimeout(() => {
        window.location.href = "/login";
      }, 1500);
    },
    onError: () => {
      toast.error("No se pudieron eliminar los datos.");
      setConfirmDelete(false);
    },
  });

  function handleDeleteClick() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    deleteMut.mutate();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5" />
          Mis datos (RGPD)
        </CardTitle>
        <CardDescription>
          Exporta una copia de todos tus datos o elimínalos permanentemente (derecho de
          portabilidad y al olvido, Art. 15/17 RGPD). Cubre tu watchlist, reglas de
          seguimiento, perfil de scoring, notificaciones, claves API y feedback.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
          className="gap-1.5"
        >
          <Download className="h-4 w-4" />
          {exportMut.isPending ? "Exportando…" : "Exportar mis datos"}
        </Button>
        <Button
          variant={confirmDelete ? "destructive" : "outline"}
          onClick={handleDeleteClick}
          disabled={deleteMut.isPending}
          className={
            confirmDelete ? "gap-1.5" : "gap-1.5 text-destructive hover:bg-destructive/10"
          }
        >
          <Trash2 className="h-4 w-4" />
          {deleteMut.isPending
            ? "Eliminando…"
            : confirmDelete
              ? "¿Confirmar eliminación?"
              : "Eliminar mis datos"}
        </Button>
        {confirmDelete && !deleteMut.isPending && (
          <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
            Cancelar
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Familias tecnológicas de la organización
// ---------------------------------------------------------------------------

/**
 * Qué vende el equipo, y por tanto qué universo puntúa el Radar por defecto.
 *
 * Hasta 2026-09 las familias del diccionario eran literales en el código: un
 * partner de Microsoft o de Salesforce heredaba el corpus y el ranking
 * pensados para SAP, sin ninguna forma de decir lo contrario. Vacío sigue
 * significando «todas», que es el comportamiento anterior.
 *
 * La lista de familias válidas la manda el backend (`tecnologias_disponibles`):
 * mantenerla aquí a mano sería la lista paralela que el invariante 3 de
 * `web/AGENTS.md` prohíbe.
 */
function TecnologiasOrganizacionCard() {
  const activeOrganizationId = useActiveOrganizationId();
  const organizations = useOrganizations();
  const { data, isLoading } = useOrganizationSettings(activeOrganizationId);
  const update = useUpdateOrganizationSettings(activeOrganizationId);

  const [seleccion, setSeleccion] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    setSeleccion(data.tecnologias ?? []); // eslint-disable-line react-hooks/set-state-in-effect
    setDirty(false);
  }, [data]);

  const rol = organizations.data?.find((o) => o.id === activeOrganizationId)?.role;
  const puedeEditar = rol === "owner" || rol === "admin";
  const disponibles = data?.tecnologias_disponibles ?? [];

  const alternar = (familia: string) => {
    setSeleccion((previa) =>
      previa.includes(familia) ? previa.filter((f) => f !== familia) : [...previa, familia],
    );
    setDirty(true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tecnologías de tu organización</CardTitle>
        <CardDescription>
          El Radar acota su universo a estas familias cuando no filtras por tecnología a mano.
          Vacío significa todas.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando familias…</p>
        ) : disponibles.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No se pudieron cargar las familias del diccionario.
          </p>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {disponibles.map((familia) => (
              <label key={familia} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={seleccion.includes(familia)}
                  disabled={!puedeEditar}
                  onCheckedChange={() => alternar(familia)}
                  aria-label={familia}
                />
                {familia}
              </label>
            ))}
          </div>
        )}

        {!puedeEditar && !isLoading && (
          <p className="text-xs text-muted-foreground">
            Solo owner o admin pueden cambiarlas.
          </p>
        )}

        {puedeEditar && (
          <Button
            size="sm"
            disabled={!dirty || update.isPending}
            onClick={() =>
              update
                .mutateAsync(seleccion)
                .then(() => {
                  setDirty(false);
                  toast.success("Tecnologías guardadas. El Radar ya usa este ámbito.");
                })
                .catch((error: unknown) =>
                  toast.error(
                    error instanceof Error ? error.message : "No se pudieron guardar",
                  ),
                )
            }
          >
            Guardar tecnologías
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Página principal
// ---------------------------------------------------------------------------

export default function MiPerfilPage() {
  const queryClient = useQueryClient();
  const activeOrganizationId = useActiveOrganizationId();

  // Carga del perfil actual
  const { data, isLoading } = useQuery<UserProfile>({
    queryKey: [...PROFILE_KEY, activeOrganizationId],
    queryFn: () =>
      fetchWithAuth<UserProfile>(
        `/api/v1/me/profile${activeOrganizationId ? `?organization_id=${activeOrganizationId}` : ""}`,
      ),
    staleTime: 60_000,
  });

  // Estado local del formulario
  const [weights, setWeights] = useState<Record<string, number>>(DEFAULT_WEIGHTS);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [kwInput, setKwInput] = useState("");
  const [cpvs, setCpvs] = useState<string[]>([]);
  const [cpvInput, setCpvInput] = useState("");
  const [importeMin, setImporteMin] = useState("");
  const [importeMax, setImporteMax] = useState("");
  const [sharedWithOrganization, setSharedWithOrganization] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Rellenar formulario cuando llegan datos del servidor
  useEffect(() => {
    if (!data) return;
    setWeights(hydrateWeights(data.weights)); // eslint-disable-line react-hooks/set-state-in-effect
    setKeywords(data.afinidad_keywords ?? []);
    setCpvs(data.cpvs ?? []);
    setImporteMin(data.importe_min != null ? String(data.importe_min) : "");
    setImporteMax(data.importe_max != null ? String(data.importe_max) : "");
    setSharedWithOrganization(data.visibility === "organization");
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
        cpvs: cpvs.length > 0 ? cpvs : null,
        importe_min: importeMin !== "" ? Number(importeMin) : null,
        importe_max: importeMax !== "" ? Number(importeMax) : null,
        organization_id: activeOrganizationId,
        visibility: sharedWithOrganization ? "organization" : "private",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      queryClient.invalidateQueries({ queryKey: ["radar", "scoring"] });
      setDirty(false);
      // Primer paso del embudo de activación («Primeros pasos» en /resumen) y
      // el que más pesa: hasta que existe este perfil, el Radar puntúa con los
      // pesos genéricos de `settings.SCORING_WEIGHTS` y el orden que ve el
      // usuario es el de otro. `primeraVez` separa esa configuración inicial de
      // los reajustes, que son uso normal. Sin propiedades del contenido: los
      // pesos, las keywords y los CPV son la estrategia comercial de quien los
      // pone, no una dimensión de producto.
      registrarEvento("perfil_configurado", { primera_vez: primeraVez("perfil") });
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
      setCpvs([]);
      setImporteMin("");
      setImporteMax("");
      setSharedWithOrganization(false);
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["radar", "scoring"] });
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

  function addCpv() {
    const cpv = cpvInput.trim();
    if (!isValidCpv(cpv) || cpvs.includes(cpv)) return;
    setCpvs((prev) => [...prev, cpv]);
    setCpvInput("");
    setDirty(true);
  }

  function removeCpv(cpv: string) {
    setCpvs((prev) => prev.filter((c) => c !== cpv));
    setDirty(true);
  }

  const hasProfile = data && (data.weights != null || data.afinidad_keywords != null || data.cpvs != null || data.importe_min != null || data.importe_max != null);

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
    <SpaceShell spaceKey="mi-perfil">
      <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="sr-only">Mi perfil de scoring</h1>
        <p className="text-muted-foreground mt-1">
          Personaliza cómo se puntúan las oportunidades. Los cambios aplican en el panel de
          detalle, el Radar y los rankings analíticos.
        </p>
        {hasProfile && (
          <p className="mt-2 text-xs text-muted-foreground">
            Última actualización:{" "}
            {data.updated_at ? formatDateTime(data.updated_at) : "—"}
          </p>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ámbito del perfil</CardTitle>
          <CardDescription>
            El Radar usa el perfil del ámbito activo. Un perfil compartido sirve como
            referencia para los miembros que no tengan uno propio.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data?.inherited && (
            <Badge variant="secondary">Perfil heredado de la organización</Badge>
          )}
          <div className="flex items-center justify-between gap-4">
            <label htmlFor="profile-visibility" className="space-y-1">
              <span className="block text-sm font-medium">Compartir con la organización</span>
              <span className="block text-xs text-muted-foreground">
                Los demás miembros podrán usar estos pesos si no han creado un perfil propio.
              </span>
            </label>
            <Switch
              id="profile-visibility"
              checked={sharedWithOrganization}
              onCheckedChange={(checked) => {
                setSharedWithOrganization(checked);
                setDirty(true);
              }}
              aria-label="Compartir perfil con la organización"
            />
          </div>
        </CardContent>
      </Card>

      <TecnologiasOrganizacionCard />

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

      {/* CPVs de interés */}
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
              onChange={(e) => setCpvInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addCpv();
                }
              }}
              className="flex-1"
            />
            <Button variant="outline" onClick={addCpv} disabled={!isValidCpv(cpvInput)}>
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
                  onClick={() => removeCpv(cpv)}
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

      <GdprSection />

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
        {hasProfile && !data?.inherited && (
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
    </SpaceShell>
  );
}
