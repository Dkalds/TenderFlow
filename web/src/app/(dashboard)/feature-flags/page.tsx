"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";

interface FeatureFlag {
  key: string;
  description: string;
  defaultEnabled: boolean;
}

const FLAGS: FeatureFlag[] = [
  {
    key: "ml_classifier_v2",
    description: "Clasificador ML v2 con transformers",
    defaultEnabled: true,
  },
  {
    key: "semantic_search",
    description: "Busqueda semantica con RAG",
    defaultEnabled: true,
  },
  {
    key: "auto_scoring",
    description: "Scoring automatico de oportunidades",
    defaultEnabled: false,
  },
  {
    key: "forecast_arima",
    description: "Prediccion ARIMA de volumen",
    defaultEnabled: false,
  },
  {
    key: "ute_detection",
    description: "Deteccion automatica de UTEs",
    defaultEnabled: false,
  },
];

export default function FeatureFlagsPage() {
  const [flagStates, setFlagStates] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(FLAGS.map((f) => [f.key, f.defaultEnabled])),
  );
  const [rollouts, setRollouts] = useState<Record<string, number>>(() =>
    Object.fromEntries(FLAGS.map((f) => [f.key, f.defaultEnabled ? 100 : 0])),
  );

  const toggleFlag = (key: string) => {
    setFlagStates((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const setRollout = (key: string, value: number) => {
    setRollouts((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Feature Flags</h1>
        <p className="text-muted-foreground">
          Toggles de funcionalidades en tiempo real.
        </p>
      </div>

      {/* Persistence banner */}
      <Card className="bg-amber-50/50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800">
        <CardContent className="pt-4 flex items-start gap-2 text-sm">
          <Info className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
          <span>
            Los feature flags se configuran localmente. Para persistencia,
            conectar al backend.
          </span>
        </CardContent>
      </Card>

      <div className="space-y-4">
        {FLAGS.map((flag) => {
          const enabled = flagStates[flag.key];
          const rollout = rollouts[flag.key];

          return (
            <Card key={flag.key}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-base font-mono">
                      {flag.key}
                    </CardTitle>
                    <CardDescription>{flag.description}</CardDescription>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={enabled ? "default" : "secondary"}>
                      {enabled ? "ON" : "OFF"}
                    </Badge>
                    <Switch
                      checked={enabled}
                      onCheckedChange={() => toggleFlag(flag.key)}
                      aria-label={`Toggle ${flag.key}`}
                    />
                  </div>
                </div>
              </CardHeader>
              {enabled && (
                <CardContent>
                  <div className="flex items-center gap-4">
                    <label className="text-sm text-muted-foreground whitespace-nowrap">
                      Rollout: {rollout}%
                    </label>
                    <Slider
                      value={[rollout]}
                      onValueChange={([v]) => setRollout(flag.key, v)}
                      min={0}
                      max={100}
                      className="flex-1"
                    />
                  </div>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
