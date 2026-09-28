"use client";

import { Component, type ReactNode } from "react";
import { PanelError } from "@/components/console/panel";

interface Props {
  children: ReactNode;
  className?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Frontera de error de los gráficos: si un gráfico revienta al dibujarse, la
 * página sigue y en su sitio queda el mismo `PanelError` que el resto de la
 * consola (mensaje humano, «Reintentar» y el detalle técnico plegado), no una
 * caja propia con otro dibujo.
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
        <PanelError
          title="No se pudo mostrar el gráfico"
          message="Algo falló al dibujarlo. Vuelve a intentarlo."
          detail={this.state.error?.message}
          onRetry={() => this.setState({ hasError: false, error: null })}
          className={this.props.className}
        />
      );
    }
    return this.props.children;
  }
}
