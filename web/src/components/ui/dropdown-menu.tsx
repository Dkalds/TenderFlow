"use client"

import * as React from "react"
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu"
import { cn } from "@/lib/utils"

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

/**
 * Envoltorio fino del `Root` de Radix, que no pinta DOM (la posición la lleva
 * el Popper de `DropdownMenuContent`). No acepta `className`: la versión hecha
 * a mano a la que sustituyó sí lo aceptaba, y durante un mes se le pasaron
 * selectores (`[&>button]:h-7`) contra un DOM que ya no existía. Ahora
 * TypeScript lo rechaza en vez de callarlo: el estilo va en el disparador.
 */
function DropdownMenu(props: React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Root>) {
  return <DropdownMenuPrimitive.Root {...props} />
}

function DropdownMenuTrigger({ className, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.Trigger>) {
  return <DropdownMenuPrimitive.Trigger className={cn("outline-none", className)} {...props} />
}

interface DropdownMenuContentProps
  extends React.ComponentProps<typeof DropdownMenuPrimitive.Content> {
  align?: "start" | "center" | "end"
}

function DropdownMenuContent({ className, align = "end", sideOffset = 4, ...props }: DropdownMenuContentProps) {
  return (
    <DropdownMenuPortal>
      <DropdownMenuPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "tf-glass-strong z-50 min-w-[8rem] overflow-hidden rounded-md border border-border p-1 text-popover-foreground shadow-md",
          // Scale from the trigger that opened it, not from center (apple-design §7 / emil-design-eng).
          "origin-[var(--radix-dropdown-menu-content-transform-origin)]",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
          className
        )}
        {...props}
      />
    </DropdownMenuPortal>
  )
}

function DropdownMenuItem({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Item> & { inset?: boolean }) {
  return (
    <DropdownMenuPrimitive.Item
      className={cn(
        "relative flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
        inset && "pl-8",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>) {
  return <DropdownMenuPrimitive.Separator className={cn("-mx-1 my-1 h-px bg-border", className)} {...props} />
}

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
}
