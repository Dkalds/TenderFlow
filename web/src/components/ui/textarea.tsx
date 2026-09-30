import * as React from "react"
import { cn } from "@/lib/utils"

export type TextareaProps = React.ComponentProps<"textarea">

function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      className={cn(
        // `text-campo` (globals.css): 16 px en móvil y 14 desde `md`, en una sola
        // clase para que el tamaño del llamador la sustituya en todos los anchos.
        "flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-campo placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
