"use client"

import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

const Sheet = DialogPrimitive.Root
const SheetTrigger = DialogPrimitive.Trigger
const SheetClose = DialogPrimitive.Close
const SheetPortal = DialogPrimitive.Portal

function SheetOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      className={cn(
        "fixed inset-0 z-50 bg-black/50 anim-duration-300 data-[state=closed]:anim-duration-200",
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        className
      )}
      {...props}
    />
  )
}

interface SheetContentProps
  extends React.ComponentProps<typeof DialogPrimitive.Content> {
  side?: "top" | "right" | "bottom" | "left"
}

/** Symmetric enter/exit path per side (apple-design §7): a panel that slides
 *  in from an edge must dismiss back the same way, never a different one. */
const SIDE_TRANSITIONS: Record<NonNullable<SheetContentProps["side"]>, string> = {
  right:
    "data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
  left:
    "data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left",
  top:
    "data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
  bottom:
    "data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
}

function SheetContent({ className, side = "right", children, ...props }: SheetContentProps) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 gap-4 bg-popover p-6 text-popover-foreground shadow-lg anim-duration-300 data-[state=closed]:anim-duration-200 focus:outline-none",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          SIDE_TRANSITIONS[side],
          side === "right" && "inset-y-0 right-0 h-full w-3/4 border-l border-border sm:max-w-sm",
          side === "left" && "inset-y-0 left-0 h-full w-3/4 border-r border-border sm:max-w-sm",
          side === "top" && "inset-x-0 top-0 border-b border-border",
          side === "bottom" && "inset-x-0 bottom-0 border-t border-border",
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2">
          <X className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">Cerrar</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </SheetPortal>
  )
}

const SheetHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col space-y-2 text-center sm:text-left", className)} {...props} />
)
SheetHeader.displayName = "SheetHeader"

function SheetTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn("text-tf-lede font-semibold text-foreground", className)} {...props} />
}

function SheetDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn("text-sm text-muted-foreground", className)} {...props} />
}

export { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetClose }
