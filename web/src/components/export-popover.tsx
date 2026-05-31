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
    const params = new URLSearchParams();
    params.set("format", format);

    // Add filter params
    if (filterParams) {
      for (const [key, value] of Object.entries(filterParams)) {
        if (value != null && value !== "") {
          params.set(key, String(value));
        }
      }
    }

    // Add extra params
    if (extraParams) {
      for (const [key, value] of Object.entries(extraParams)) {
        params.set(key, value);
      }
    }

    const url = `${endpoint}?${params.toString()}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
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
