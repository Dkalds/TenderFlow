import { FichaEsqueleto } from "./_components/ficha-esqueleto";

/**
 * Esqueleto de ruta de la ficha. Es el que se ve al abrir una oportunidad desde
 * el tablero o desde otra ficha: el prefetch del `<Link>` se detiene aquí, y
 * enseña lo mismo que la página mientras pide la oportunidad (el porqué, en
 * `ficha-esqueleto.tsx`).
 */
export default function OportunidadLoading() {
  return <FichaEsqueleto />;
}
