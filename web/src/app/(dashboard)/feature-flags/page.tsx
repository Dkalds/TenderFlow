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
import { Separator } from "@/components/ui/separator";
import { ToggleRight, Info } from "lucide-react";

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
    Object.fromEntries(FLAGS.map((f) => [f.key, f.defaultEnabled]))
  );
  const [rollouts, setRollouts] = useState<Record<string, number>>(() =>
    Object.fromEntries(FLAGS.map((f) => [f.key, f.defaultEnabled ? 100 : 0]))
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

      <Card className="bg-blue-50/50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-800">
        <CardContent className="pt-4 flex items-start gap-2 text-sm">
          <Info className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
          <span>
            Feature flags se persisten en la base de datos. Esta interfaz es de solo
            lectura en la version actual.
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
                    <CardTitle className="text-base font-mono">{flag.key}</CardTitle>
                    <CardDescription>{flag.description}</CardDescription>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={enabled ? "default" : "secondary"}>
                      {enabled ? "ON" : "OFF"}
                    </Badge>
                    {/* Toggle switch */}
                    <button
                      onClick={() => toggleFlag(flag.key)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        enabled ? "bg-primary" : "bg-muted-foreground/30"
                      }`}
                      role="switch"
                      aria-checked={enabled}
                    >
                      <span
                        className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                          enabled ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <label className="text-sm text-muted-foreground whitespace-nowrap">
                    Rollout: {rollout}%
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={rollout}
                    onChange={(e) => setRollout(flag.key, parseInt(e.target.value, 10))}
                    className="flex-1 h-2 accent-primary"
                  />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
