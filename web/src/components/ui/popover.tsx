"use client"

import * as React from "react"
import * as PopoverPrimitive from "@radix-ui/react-popover"
import { cn } from "@/lib/utils"

const Popover = PopoverPrimitive.Root
const PopoverTrigger = PopoverPrimitive.Trigger
const PopoverAnchor = PopoverPrimitive.Anchor

/**
 * Use over `DropdownMenu` when the content needs a text input or other
 * form control — `DropdownMenu` is a Radix `Menu` under the hood (roving
 * focus + typeahead search across items), which fights typing in an
 * `<input>`. `Popover` is a plain dismissible, focus-trapped layer with
 * none of that, so it composes cleanly with forms (see SavedViewsMenu).
 */
function PopoverContent({
  className,
  align = "end",
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "tf-glass-strong z-50 w-72 rounded-xl border border-border/70 p-2 text-popover-foreground shadow-md outline-none",
          // Scale from the trigger that opened it, not from center (apple-design §7 / emil-design-eng).
          "origin-[var(--radix-popover-content-transform-origin)]",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}

export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent }
