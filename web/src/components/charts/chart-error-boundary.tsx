"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  children: ReactNode;
  className?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error boundary specifically designed for chart components.
 * Shows a compact retry UI that matches the chart container size.
 */
export class ChartErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className={cn(
            "flex flex-col items-center justify-center gap-3 rounded-md border border-dashed border-destructive/30 bg-destructive/5 p-6",
            this.props.className,
          )}
          role="alert"
        >
          <AlertTriangle className="h-8 w-8 text-destructive/60" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">{"No se pudo cargar el gráfico."}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            {"Reintentar"}
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
