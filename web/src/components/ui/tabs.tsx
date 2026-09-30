"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

/**
 * Pestañas sobre Radix (flechas, roving tabindex y `aria-controls` de serie),
 * con la piel de la consola: la misma geometría que `PanelTabs` y `Segmented`
 * (`clasePestana` de `@/components/console/panel`). Sin la pista gris ni el
 * activo blanco con sombra de shadcn: «cambiar de vista» se dibuja igual en
 * toda la app.
 *
 * Las clases están escritas aquí y no importadas de la consola para que `ui/`
 * no dependa de `console/`; si cambia `clasePestana`, cambia esto también.
 */
const Tabs = TabsPrimitive.Root;

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex flex-wrap items-center gap-0.5", className)} {...props} />;
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-2.5 text-tf-meta font-medium text-muted-foreground transition-colors md:h-7",
        "hover:text-foreground disabled:pointer-events-none disabled:opacity-50 [&_svg]:h-3.5 [&_svg]:w-3.5 [&_svg]:flex-none",
        "data-[state=active]:border-border/70 data-[state=active]:bg-secondary data-[state=active]:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      // Sin fundido de entrada: cambiar de pestaña es un gesto de consulta
      // diaria, y el contenido tiene que estar ahí en el mismo frame del clic.
      className={cn("mt-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring", className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
