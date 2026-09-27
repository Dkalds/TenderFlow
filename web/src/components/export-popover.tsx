"use client";

import * as React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { useFilterParams } from "@/lib/filters";
import { buildExportUrl, triggerDownload } from "@/lib/export";

interface ExportPopoverProps {
  endpoint?: string;
  extraParams?: Record<string, string>;
  /**
   * @deprecated Se aplica al disparador. Los `[&>button]:…` que le pasaban
   * algunas pantallas para achicarlo nunca llegaron a nada; la talla la da
   * `size`.
   */
  className?: string;
  /**
   * Etiqueta del disparador. Por defecto «Exportar»; la barra de ámbito la
   * cambia a «Exportar ámbito», y cada exportación de sección nombra su objeto
   * («Exportar competidores», «Exportar órganos»…): dos botones iguales no se
   * distinguen.
   */
  label?: string;
  /** Talla del disparador: `sm` (la de la consola, por defecto) o `default`. */
  size?: "sm" | "default";
}

/**
 * Exportación del ámbito o de una sección a CSV o Excel. El disparador es un
 * botón `outline` de la talla de la consola: mismo alto que el resto de la
 * barra en la que vive.
 */
export function ExportPopover({
  endpoint = "/api/v1/exports/download",
  extraParams,
  className,
  label = "Exportar",
  size = "sm",
}: ExportPopoverProps) {
  const filterParams = useFilterParams();

  // `format` es el parámetro de la API, no la extensión: el Excel se pide como
  // `excel` y se recibe como `.xlsx`. Pedirlo como `xlsx` devolvía un 422.
  const handleExport = (format: "csv" | "excel") => {
    const url = buildExportUrl(endpoint, format, filterParams, extraParams);
    void triggerDownload(url);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className={cn(buttonVariants({ variant: "outline", size }), className)}>
        <Download aria-hidden="true" />
        {label}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => handleExport("csv")}>
          <FileText aria-hidden="true" />
          Exportar CSV
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => handleExport("excel")}>
          <FileSpreadsheet aria-hidden="true" />
          Exportar Excel
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
