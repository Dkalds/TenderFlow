import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Deja seleccionada la fila del Radar cuyo título es *titulo* y la devuelve.
 *
 * Es el mismo gesto que `seleccionarFila` de `critical-workflows.spec.ts`, que
 * cuenta el porqué entero: las acciones de una fila inactiva son `inert` y, en
 * la tabla, `pointer-events-none`, así que «Abrir» o «Descartar» no están en
 * el árbol de accesibilidad hasta que la fila es la activa. Vive aparte porque
 * la usan dos recorridos y aquel spec no exporta la suya.
 *
 * La fila se localiza por `[data-active]`, que en esta pantalla solo lo lleva
 * `radar-fila.tsx`: el título también está en el inspector de la derecha, y un
 * `getByText` a secas se iría allí en cuanto hay fila activa.
 */
export async function seleccionarFilaDelRadar(page: Page, titulo: string): Promise<Locator> {
  const fila = filaDelRadar(page, titulo);
  await expect(fila, `la fila «${titulo}» no aparece en el Radar`).toBeVisible({
    timeout: 20_000,
  });
  await fila.getByRole("button", { name: `Seleccionar ${titulo}` }).click();
  await expect(fila).toHaveAttribute("data-active", "true");
  return fila;
}

/** La fila de *titulo* en la bandeja que esté a la vista, exista o no. */
export function filaDelRadar(page: Page, titulo: string): Locator {
  return page.locator("[data-active]").filter({ hasText: titulo });
}
