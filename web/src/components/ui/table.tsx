import * as React from "react"
import { cn } from "@/lib/utils"

/**
 * Cabecera de columna de tabla: el único rótulo de la consola que va en
 * versal. Sans, 11 px, seminegrita, con un tracking corto (0,04em) que abre la
 * versal lo justo. Es `TableHead`, y lo usan también las tablas hechas a mano
 * (`<th className={CABECERA_COLUMNA}>`) y las cabeceras de lista que imitan una
 * tabla. Si la cabecera es un `<button>` (ordenable), la clase va en el botón:
 * el navegador pone `text-transform: none` a los botones y no la heredan.
 *
 * Antes era mono a 9 px con 0,1em, por debajo del suelo de 11 px de la escala.
 */
export const CABECERA_COLUMNA =
  "text-tf-micro font-semibold uppercase tracking-[0.04em] text-muted-foreground"

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement>
>(({ className, ...props }, ref) => (
  <div className="relative w-full overflow-auto">
    <table
      ref={ref}
      // 13 px (tf-body), no 14: la tabla de la consola es densa y tabular, y un
      // punto menos es lo que mete cuatro filas más en pantalla sin tocar la
      // legibilidad.
      className={cn("w-full caption-bottom text-tf-body", className)}
      {...props}
    />
  </div>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
      className
    )}
    {...props}
  />
))
TableFooter.displayName = "TableFooter"

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      // Tintes de la escala: /5 al pasar, /10 la fila seleccionada. 110 ms,
      // solo color: una fila se cruza con el ratón decenas de veces por minuto
      // (docs/frontend-motion.md).
      "border-b border-border/30 transition-colors duration-110 hover:bg-primary/5 data-[state=selected]:bg-primary/10",
      className
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    data-slot="table-head"
    className={cn(
      "h-8 px-2 text-left align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
      CABECERA_COLUMNA,
      className
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement> & {
    /** Columna de cifras: alineada a la derecha (las cifras ya son tabulares). */
    numeric?: boolean
  }
>(({ className, numeric, ...props }, ref) => (
  <td
    ref={ref}
    data-slot="table-cell"
    className={cn(
      // Cifras siempre tabulares: sin `tnum` las columnas de importe bailan al
      // cambiar de página y se pierde la comparación vertical, que es para lo
      // que existe una tabla.
      "px-2 py-1.5 align-middle tabular-nums [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
      numeric && "text-right",
      className
    )}
    {...props}
  />
))
TableCell.displayName = "TableCell"

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-tf-meta text-muted-foreground", className)}
    {...props}
  />
))
TableCaption.displayName = "TableCaption"

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
