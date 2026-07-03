"use client";

import * as React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { useFilterParams } from "@/lib/filters";
import { buildExportUrl, triggerDownload } from "@/lib/export";

interface ExportPopoverProps {
  endpoint?: string;
  extraParams?: Record<string, string>;
  className?: string;
}

export function ExportPopover({
  endpoint = "/api/v1/exports/download",
  extraParams,
  className,
}: ExportPopoverProps) {
  const filterParams = useFilterParams();

  const handleExport = (format: "csv" | "xlsx") => {
    const url = buildExportUrl(endpoint, format, filterParams, extraParams);
    triggerDownload(url);
  };

  return (
    <DropdownMenu className={cn(className)}>
      <DropdownMenuTrigger className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
        <Download aria-hidden="true" className="h-4 w-4" />
        Exportar
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => handleExport("csv")}>
          <FileText aria-hidden="true" className="h-4 w-4" />
          Exportar CSV
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => handleExport("xlsx")}>
          <FileSpreadsheet aria-hidden="true" className="h-4 w-4" />
          Exportar Excel
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
