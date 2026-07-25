"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { cn } from "@/lib/utils"

/**
 * Mount once near the app root. `skipDelayDuration` is the specific rule
 * from emil-design-eng: the *first* tooltip in a group waits `delayDuration`
 * (avoids accidental activation while moving the pointer across a toolbar),
 * but once one tooltip has shown, adjacent tooltips within
 * `skipDelayDuration` open instantly — this is what makes hovering across a
 * row of icon buttons feel fast without defeating the point of the initial
 * delay.
 */
const TooltipProvider = ({
  delayDuration = 300,
  skipDelayDuration = 300,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) => (
  <TooltipPrimitive.Provider
    delayDuration={delayDuration}
    skipDelayDuration={skipDelayDuration}
    {...props}
  />
)

const Tooltip = TooltipPrimitive.Root
const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "tf-glass-strong z-50 overflow-hidden rounded-md border border-border px-2.5 py-1.5 text-xs text-popover-foreground shadow-md",
      // Scale from the trigger, not center (apple-design §7 / emil-design-eng).
      "origin-[var(--radix-tooltip-content-transform-origin)]",
      "data-[state=delayed-open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=delayed-open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=delayed-open]:zoom-in-95",
      className
    )}
    {...props}
  />
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
